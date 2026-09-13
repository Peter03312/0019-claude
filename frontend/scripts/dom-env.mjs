// 必须在任何 vue 模块求值前运行：runtime-dom 在模块加载时缓存 document。
import { Window } from 'happy-dom'

const window = new Window({ url: 'http://localhost/' })
globalThis.window = window
for (const key of [
  'document', 'Document', 'ShadowRoot', 'navigator', 'HTMLElement', 'SVGElement',
  'Element', 'Node', 'Text', 'Comment', 'Event', 'CustomEvent',
  'MutationObserver', 'DocumentFragment', 'getComputedStyle',
]) {
  if (window[key]) globalThis[key] = window[key]
}
globalThis.fetch = () => { throw new Error('fetch must be mocked per test') }
