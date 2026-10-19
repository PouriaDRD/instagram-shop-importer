const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(__dirname + '/../../app/templates/index.html', 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
const source = scripts[scripts.length - 1][1].replace('{{ crawl_stop_token|tojson }}', '"TEST"');
new vm.Script(source);
const KEY = 'selora-importer-active-crawl-rc54';
async function scenario({resumed = false, statuses = ['completed']}) {
  const dom = new Map();
  const events = new Map();
  const make = (id) => ({
    id, value: id === 'username' ? 'shop' : id === 'max_items' ? '5' : id === 'sort_order' ? 'newest' : '',
    disabled: false, hidden: id === 'crawlViewResults', href: null, textContent: '', style: {},
    classList: { add(){}, remove(){} }, setAttribute(){}, focus(){},
    addEventListener(name, cb) {events.set(`${id}:${name}`, cb)}
  });
  const ids=['crawlForm','username','max_items','sort_order','instagram_account','crawlSubmitButton','crawlButtonText','crawlStatus','crawlStatusTitle','crawlStatusDescription','crawlStopButton','crawlProgressTrack','crawlProgressFill','crawlViewResults'];
  for(const id of ids) dom.set(id, make(id));
  dom.get('crawlForm').action = '/crawl';
  const store = new Map();
  if(resumed) store.set(KEY, JSON.stringify({status_url:'/crawl/abc/status',stop_url:'/crawl/abc/stop'}));
  const locations=[];
  let reads=0;
  const window = {setTimeout(cb){setImmediate(cb)}, location:{assign(url){locations.push(url)}}};
  const fetch = async (url,opts)=>{
    if(url === '/crawl') return {ok:true,status:202,json:async()=>({id:'abc',username:'shop',status_url:'/crawl/abc/status'})};
    if(url.endsWith('/status')){
      const status = statuses[Math.min(reads++, statuses.length-1)];
      return {ok:true,status:200,json:async()=>({status,username:'shop',crawled_media_count:5,detail_url:'/crawl/abc',progress:{}})};
    }
    throw Error('unexpected fetch '+url);
  };
  const context={window,document:{getElementById(id){return dom.get(id)}},sessionStorage:{getItem:k=>store.get(k) || null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},FormData: class{},fetch,console,setImmediate,setTimeout,Number,JSON,Error,Promise};
  vm.createContext(context);
  vm.runInContext(source, context);
  if(!resumed){
    const submit = events.get('crawlForm:submit');
    assert(submit);
    await submit({preventDefault(){},stopPropagation(){}});
  }
  for(let i=0;i<12;i++) await new Promise(resolve=>setImmediate(resolve));
  return {dom,store,locations,reads};
}
(async()=>{
  let result=await scenario({resumed:true});
  assert.strictEqual(result.store.has(KEY),false,'resumed job should clear stale resume state');
  assert.deepStrictEqual(result.locations,[],'resumed completion must not redirect');
  assert.strictEqual(result.dom.get('crawlViewResults').href,'/crawl/abc');
  assert.strictEqual(result.dom.get('crawlViewResults').hidden,false);
  assert.strictEqual(result.dom.get('crawlSubmitButton').disabled,false);
  assert.strictEqual(result.reads,1);
  console.log('[PASS] completed stale job shows results link, no navigation loop');
  result=await scenario({resumed:false,statuses:['running','completed']});
  assert.deepStrictEqual(result.locations,['/crawl/abc'],'new job should navigate only once');
  assert.strictEqual(result.store.has(KEY),false,'new completion must clear resume before navigation');
  assert.strictEqual(result.reads,2);
  console.log('[PASS] freshly completed job navigates once after clearing resume state');
  result=await scenario({resumed:true,statuses:['running','completed']});
  assert.strictEqual(result.store.has(KEY),false);
  assert.deepStrictEqual(result.locations,[]);
  assert.strictEqual(result.reads,2);
  console.log('[PASS] resumed active crawl completing later does not redirect');
})().catch(e=>{console.error(e);process.exitCode=1});
