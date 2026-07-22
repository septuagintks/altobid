// ==UserScript==
// @name         altobid 验证码自动答题
// @namespace    https://github.com/septuagintks/altobid
// @version      0.2.0
// @description  抓取出价弹窗的题干与图片，交给本地 Qwen2.5-VL 服务作答，自动回填输入框
// @author       Septuagint
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @connect      aliyuncs.com
// @connect      *
// @run-at       document-start
// ==/UserScript==

/*
 * 说明：
 * - @match 用通配占位，安装时请按真实目标站点收窄（如 https://目标域名/*）。
 * - 需先启动本地服务：python -m altobid.server（默认 127.0.0.1:8799）。
 * - 题目图常在跨域 OSS（如 *.aliyuncs.com），@connect * 放行跨域取图；
 *   若想收紧，删掉 @connect * 只保留实际图床域名即可。
 * - 未加 @noframes：弹窗可能在 iframe 内渲染，脚本需在子框架也运行才能抓到。
 * - 只依赖 4 个稳定锚点：.whSetPriceD / .whpdtip / img.pricecaptcha / #bidprice，
 *   容器 class、按钮、alt、autocomplete 的差异一律忽略，以吸收目标站差异。
 * - 仅回填答案，不自动点「确定」提交。
 *
 * 排障：DEBUG=true 时控制台打印每一步 [altobid] 面包屑。若某步没打印，
 * 问题就在上一步（脚本没跑 / 没找到弹窗 / 请求被拦）。定位后可关掉。
 */

(function () {
  'use strict';

  const HOST = 'http://127.0.0.1:8799';
  const SOLVE = HOST + '/solve';
  const HEALTH = HOST + '/health';
  const TAG = '[altobid]';
  const DEBUG = false;  // 排障时改 true，控制台会打印每一步 [altobid] 面包屑

  const dbg = (...a) => DEBUG && console.log(TAG, ...a);

  // 确认 GM_xmlhttpRequest 存在（@grant 缺失/被油猴禁用时它是 undefined）
  const GMX =
    typeof GM_xmlhttpRequest !== 'undefined' ? GM_xmlhttpRequest
    : (typeof GM !== 'undefined' && GM.xmlHttpRequest) ? GM.xmlHttpRequest
    : null;

  dbg('脚本已注入', location.href, 'GM_xmlhttpRequest=', !!GMX);
  if (!GMX) {
    console.error(TAG, 'GM_xmlhttpRequest 不可用：检查 @grant 与油猴权限设置');
  }

  // ---- 与本地服务通信（GM_xmlhttpRequest 绕过页面 CORS）--------------------

  function gmRequest(opts) {
    return new Promise((resolve, reject) => {
      GMX({
        ...opts,
        onload: resolve,
        onerror: (e) => reject(new Error('请求失败: ' + opts.url + ' ' + JSON.stringify(e && e.error || ''))),
        ontimeout: () => reject(new Error('请求超时: ' + opts.url)),
      });
    });
  }

  async function checkHealth() {
    try {
      const r = await gmRequest({ method: 'GET', url: HEALTH, timeout: 3000 });
      dbg('health 响应', r.status, r.responseText);
      return JSON.parse(r.responseText).ready === true;
    } catch (e) {
      console.error(TAG, 'health 请求失败（本地服务没起？跨域没放行？）:', e);
      return false;
    }
  }

  // src -> dataURL（base64）。GM 取图可携带站点 cookie、绕过 canvas 跨域污染。
  async function fetchImage(src) {
    const r = await gmRequest({
      method: 'GET', url: src, responseType: 'blob', timeout: 15000,
    });
    if (r.status && (r.status < 200 || r.status >= 300)) {
      throw new Error('取图 HTTP ' + r.status + ': ' + src);
    }
    if (!r.response || !/^image\//.test(r.response.type || '')) {
      throw new Error('取图返回非图片: ' + (r.response && r.response.type));
    }
    return await new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onloadend = () => resolve(fr.result);
      fr.onerror = () => reject(new Error('图片读取失败'));
      fr.readAsDataURL(r.response);
    });
  }

  async function solve(image, prompt) {
    const r = await gmRequest({
      method: 'POST', url: SOLVE, timeout: 60000,
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({ image, prompt }),
    });
    const body = JSON.parse(r.responseText);
    if (r.status !== 200) throw new Error(body.error || ('HTTP ' + r.status));
    return body.answer;
  }

  // ---- DOM 抓取与回填 -----------------------------------------------------

  // 只依赖稳定锚点，容器 class 差异一律忽略
  function extract(box) {
    const tip = box.querySelector('.whpdtip');
    // textContent：site1 是裸文本节点，且隐藏元素 innerText 会为空
    const text = tip ? tip.textContent.trim() : '';
    const hidden = tip && getComputedStyle(tip).display === 'none';
    const prompt = (hidden || text === 'noprompt') ? '' : text;
    const img = box.querySelector('img.pricecaptcha');
    const input = box.querySelector('#bidprice');
    return { prompt, img, input };
  }

  // 等 src 被填上就返回其绝对 URL（img.src 属性已由浏览器解析为绝对地址）。
  // 关键：不依赖 <img> 在页面里加载成功——跨域/混合内容(http 图 on https 页)会让
  // img 渲染失败(naturalWidth=0)甚至报 error，但 GM_xmlhttpRequest 仍能取到字节，
  // 所以只等 src 就绪，取图交给 GM。
  function waitImageSrc(img, timeout = 10000) {
    const ready = () => img.getAttribute('src') && img.src && img.src !== location.href;
    if (ready()) return Promise.resolve(img.src);
    return new Promise((resolve, reject) => {
      const obs = new MutationObserver(() => {
        if (ready()) { obs.disconnect(); clearTimeout(timer); resolve(img.src); }
      });
      obs.observe(img, { attributes: true, attributeFilter: ['src'] });
      const timer = setTimeout(() => {
        obs.disconnect();
        reject(new Error('图片 src 迟迟未就绪'));
      }, timeout);
    });
  }

  // React 受控输入：直接 .value= 不触发状态更新，需原生 setter + input 事件
  function fill(input, value) {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // ---- 主流程 -------------------------------------------------------------

  async function handle(box) {
    dbg('发现弹窗 .whSetPriceD，开始抓题', box);
    const { prompt, img, input } = extract(box);
    dbg('抓题结果 prompt=', prompt || '(无)', 'img=', img && img.src, 'input=', !!input);
    if (!img || !input) {
      console.warn(TAG, '未找到图片(img.pricecaptcha)或输入框(#bidprice)，跳过', box);
      box.dataset.altobidDone = '';
      return;
    }
    if (!(await checkHealth())) {
      console.warn(TAG, '本地服务未就绪，请先启动 python -m altobid.server（并确认油猴已放行到 127.0.0.1 的请求）');
      box.dataset.altobidDone = '';
      return;
    }
    try {
      const src = await waitImageSrc(img);
      dbg('图片 src 就绪，取图中', src);
      const image = await fetchImage(src);
      dbg('取图完成，base64 长度', image.length, '请求推理中');
      const answer = await solve(image, prompt);
      fill(input, answer);
      console.info(TAG, 'prompt=', prompt || '(无)', '-> answer=', answer);
    } catch (e) {
      console.error(TAG, '处理失败:', e);
      box.dataset.altobidDone = '';  // 允许下次重试
    }
  }

  function scan(root) {
    (root || document).querySelectorAll('.whSetPriceD').forEach((box) => {
      if (box.dataset.altobidDone) return;
      box.dataset.altobidDone = '1';
      handle(box);
    });
  }

  // 弹窗为动态插入，监听 DOM 变化；DOM 就绪后也扫一次（脚本晚于弹窗注入的情况）
  function start() {
    dbg('启动监听');
    new MutationObserver(() => scan()).observe(document.documentElement, {
      childList: true, subtree: true,
    });
    scan();
  }
  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start, { once: true });
})();
