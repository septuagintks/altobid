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
// @run-at       document-idle
// @noframes
// ==/UserScript==

/*
 * 说明：
 * - @match 用通配占位，安装时请按真实目标站点收窄（如 https://目标域名/*）。
 * - 需先启动本地服务：python -m altobid.server（默认 127.0.0.1:8799）。
 * - 只依赖 4 个稳定锚点：.whSetPriceD / .whpdtip / img.pricecaptcha / #bidprice，
 *   容器 class、按钮、alt、autocomplete 的差异一律忽略，以吸收目标站差异。
 * - 仅回填答案，不自动点「确定」提交。
 */

(function () {
  'use strict';

  const HOST = 'http://127.0.0.1:8799';
  const SOLVE = HOST + '/solve';
  const HEALTH = HOST + '/health';
  const TAG = '[altobid]';

  // ---- 与本地服务通信（GM_xmlhttpRequest 绕过页面 CORS）--------------------

  function gmRequest(opts) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        ...opts,
        onload: resolve,
        onerror: () => reject(new Error('请求失败: ' + opts.url)),
        ontimeout: () => reject(new Error('请求超时: ' + opts.url)),
      });
    });
  }

  async function checkHealth() {
    try {
      const r = await gmRequest({ method: 'GET', url: HEALTH, timeout: 3000 });
      return JSON.parse(r.responseText).ready === true;
    } catch (_) {
      return false;
    }
  }

  // src -> dataURL（base64）。GM 取图可携带站点 cookie、绕过 canvas 跨域污染。
  async function fetchImage(src) {
    const r = await gmRequest({
      method: 'GET', url: src, responseType: 'blob', timeout: 15000,
    });
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

  // 图片可能异步加载，等就绪再返回 src（已是浏览器解析后的绝对 URL）
  function waitImage(img) {
    if (img.complete && img.naturalWidth > 0) return Promise.resolve(img.src);
    return new Promise((resolve, reject) => {
      img.addEventListener('load', () => resolve(img.src), { once: true });
      img.addEventListener('error', () => reject(new Error('图片加载失败')), { once: true });
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
    const { prompt, img, input } = extract(box);
    if (!img || !input) {
      console.warn(TAG, '未找到图片或输入框，跳过');
      box.dataset.altobidDone = '';
      return;
    }
    if (!(await checkHealth())) {
      console.warn(TAG, '本地服务未就绪，请先启动 python -m altobid.server');
      box.dataset.altobidDone = '';
      return;
    }
    try {
      const src = await waitImage(img);
      const image = await fetchImage(src);
      const answer = await solve(image, prompt);
      fill(input, answer);
      console.info(TAG, 'prompt=', prompt || '(无)', '-> answer=', answer);
    } catch (e) {
      console.error(TAG, e);
      box.dataset.altobidDone = '';  // 允许下次重试
    }
  }

  function scan() {
    document.querySelectorAll('.whSetPriceD').forEach((box) => {
      if (box.dataset.altobidDone) return;
      box.dataset.altobidDone = '1';
      handle(box);
    });
  }

  // 弹窗为动态插入，监听 DOM 变化；启动时也扫一次（脚本晚于弹窗注入的情况）
  new MutationObserver(scan).observe(document.body, {
    childList: true, subtree: true,
  });
  scan();
})();
