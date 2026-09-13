// 动态竞态回归：挂载真实 App.vue，mock fetch 控制响应到达顺序。
// 用法：node scripts/race-test.mjs
import './dom-env.mjs'
// 生产版 vue 不暴露 setup 绑定；测试需驱动组件状态，统一用 dev 构建
import { createApp, nextTick } from '../node_modules/vue/dist/vue.esm-browser.js'
import { parse, compileScript } from '@vue/compiler-sfc'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const VUE_DEV = '../../node_modules/vue/dist/vue.esm-browser.js'
const APP_SOURCE = process.env.APP_SOURCE
  ? resolve(process.env.APP_SOURCE)
  : resolve(root, 'src/App.vue')

// 编译 SFC（内联模板）。为让测试驱动 setup 绑定，在编译产物的 setup 末尾插入
// __expose（defineExpose 的底层调用），仅插桩测试产物，不改产品源码。
function compileVue(file) {
  const source = readFileSync(file, 'utf8')
  const { descriptor } = parse(source, { filename: file })
  const script = compileScript(descriptor, { id: 'race', inlineTemplate: true })
  let code = script.content.replace(/from ['"]vue['"]/g, `from '${VUE_DEV}'`)

  const raw = descriptor.scriptSetup?.content ?? ''
  const setupLines = raw.split('\n')
  const names = new Set()
  let depth = 0
  for (const line of setupLines) {
    // 只收集缩进为 0（setup 顶层）的 const/function 绑定，跳过函数内局部变量
    const m = line.match(/^(?:const|let|var)\s+([A-Za-z_$][\w$]*)/)
      ?? line.match(/^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/)
    if (m && depth === 0) names.add(m[1])
    depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length
  }
  if (names.size && /setup\(__props\)/.test(code)) {
    code = code.replace(/setup\(__props\)\s*\{/, 'setup(__props, { expose: __expose }) {')
    // setup 体在顶层 return (_ctx, _cache) => 之前结束；把 expose 插在该 return 前
    code = code.replace(
      /\nreturn \(_ctx, _cache\)/,
      `\n__expose({ ${[...names].join(', ')} });\nreturn (_ctx, _cache)`
    )
  }
  return code
}

const genDir = resolve(root, 'scripts/.gen')
mkdirSync(genDir, { recursive: true })
writeFileSync(resolve(genDir, 'ResultView.mjs'), compileVue(resolve(root, 'src/components/ResultView.vue')))
const appCode = compileVue(APP_SOURCE).replace(
  /from ['"]\.\/components\/ResultView\.vue['"]/,
  `from './ResultView.mjs'`
)
const appFile = resolve(genDir, 'App.mjs')
writeFileSync(appFile, appCode)

const { default: App } = await import(pathToFileURL(appFile).href)

const container = document.createElement('div')
document.body.appendChild(container)
const appInst = createApp(App)
const s = appInst.mount(container) // 经公共代理：ref 自动解包，expose 后的绑定可读写

let failures = 0
function check(label, cond) {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}`)
  if (!cond) failures++
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}
const JUDGE_A = {
  wet_mass: '8.640', dry_masses: ['8.000', '8.000', '8.000'],
  constant: true, hit_round: 1, endpoint_index: 2, endpoint_mass: '8.000',
  rounds: [{ round: 1, prev_index: 1, curr_index: 2, prev_mass: '8.000',
    curr_mass: '8.000', loss: '0', ratio: '0', ratio_display: '0.000000',
    threshold: '0.0005', status: 'hit' }],
  regain: '8.00', regain_exact: '8', qualified: true, conclusion: '合格',
  formula: 'fA',
}
const JUDGE_B = { ...JUDGE_A, conclusion: '越界', qualified: false,
  regain: '8.51', formula: 'fB' }

function installFetch(handlers) {
  let i = 0
  globalThis.fetch = async (url, opts) => handlers[i++](url, opts)
}
function deferred(body, status = 200) {
  let fire
  const p = new Promise((res) => { fire = () => res(jsonResponse(body, status)) })
  return { p, fire }
}
async function flush(n = 4) { for (let i = 0; i < n; i++) await nextTick() }

// ============ 故障 2：裁决响应前改读数，旧裁决不得重现 ============
{
  const d1 = deferred(JUDGE_A)
  installFetch([() => d1.p])

  s.wetMass = '8.640'
  s.dryMasses.splice(0, s.dryMasses.length,
    { value: '8.000' }, { value: '8.000' }, { value: '8.000' })
  await flush()
  s.submit()                          // 发射后不管：响应由 deferred 手动放行
  await flush()
  check('故障2: 提交后进入等待态', s.loading === true)

  s.dryMasses[0].value = '8.100'      // 响应回来前修改读数
  await flush()
  check('故障2: 改读数后结果立即清空', s.result === null)
  check('故障2: 改读数后退出等待态', s.loading === false)

  d1.fire()                           // 旧输入的响应现在才到
  await d1.p; await flush()
  check('故障2: 迟到的旧裁决不显示', s.result === null)
  check('故障2: 无旧错误回显', s.topError === '')
}

// ============ 故障 3：保存响应前改读数并重裁，旧保存提示不得出现 ============
{
  const dSave = deferred({ ...JUDGE_B, sample_id: 'OLD/1', saved_at: '2026-01-01T00:00:00+00:00' }, 201)
  const dJudge = deferred(JUDGE_B)
  installFetch([() => dSave.p, () => dJudge.p])

  s.result = JUDGE_A                 // 造出一份已完成的当前裁决
  s.sampleId = 'OLD/1'
  await flush()
  s.saveRecord()                     // 发射后不管
  await flush()
  check('故障3: 保存中', s.saving === true)

  s.dryMasses[1].value = '7.900'     // 响应前改读数
  await flush()
  check('故障3: 改读数后裁决清空', s.result === null)
  check('故障3: 旧保存成功提示未提前出现', s.saveOk === '')
  check('故障3: 退出保存等待态', s.saving === false)

  dSave.fire()                        // 旧保存响应迟到
  await dSave.p; await flush()
  check('故障3: 迟到的旧保存成功提示不显示', s.saveOk === '')
  check('故障3: 迟到响应不产生错误提示', s.saveError === '')

  s.submit()                          // 对新输入重新裁决（发射后不管）
  await flush()
  dJudge.fire()
  await dJudge.p; await flush()
  check('故障3: 新输入裁决正常显示', s.result?.formula === 'fB')
  check('故障3: 新裁决旁没有旧保存提示', s.saveOk === '')
}

// ============ 故障 4：连续两次查询，慢的首响应不得覆盖最后一次结果 ============
{
  const dQ1 = deferred({ ...JUDGE_A, sample_id: 'FIRST/1', saved_at: 't1' })
  const dQ2 = deferred({ ...JUDGE_B, sample_id: 'SECOND/2', saved_at: 't2' })
  installFetch([() => dQ1.p, () => dQ2.p])

  s.queryId = 'FIRST/1'
  s.queryRecord()
  await flush()
  check('故障4: 首次查询进入等待', s.querying === true)

  s.queryId = 'SECOND/2'
  s.queryRecord()                     // 第二个查询在首响应前发起
  await flush()

  dQ1.fire()                          // 首请求更慢：现在才返回
  await dQ1.p; await flush()
  check('故障4: 较早查询的记录不显示', s.record?.sample_id !== 'FIRST/1')
  check('故障4: 旧响应不得提前结束等待态', s.querying === true)

  dQ2.fire()
  await dQ2.p; await flush()
  check('故障4: 最终保留最后一次查询的结果', s.record?.sample_id === 'SECOND/2')
  check('故障4: 查询结束', s.querying === false)
  check('故障4: 无错误提示', s.queryError === '')
}

// 额外：第二次查询 404 时第一次的成功结果也不得“复活”
{
  const dA = deferred({ ...JUDGE_A, sample_id: 'X/1', saved_at: 't' })
  const dB = deferred({ detail: '未找到试样编号「X/2」的记录' }, 404)
  installFetch([() => dA.p, () => dB.p])
  s.queryId = 'X/1'
  s.queryRecord()
  await flush()
  s.queryId = 'X/2'
  s.queryRecord()
  await flush()
  dA.fire(); await dA.p; await flush()
  check('补充: 慢的旧成功响应不复活', s.record === null)
  dB.fire(); await dB.p; await flush()
  check('补充: 最后一次 404 提示生效', s.queryError.includes('X/2'))
}

appInst.unmount()
if (failures) { console.error(`\n${failures} 项检查失败`); process.exit(1) }
console.log('\n全部竞态检查通过')
