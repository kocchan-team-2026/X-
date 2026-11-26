const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=t=>t?t.replace('T',' ').slice(0,16).replace(/-/g,'/'):'不明';
async function api(path,opt){const r=await fetch(path,opt);if(!r.ok)throw new Error((await r.text())||('HTTP '+r.status));return r.json();}
function toast(msg,err){const d=document.createElement('div');d.className='toast'+(err?' err':'');d.textContent=msg;$('#toast').append(d);setTimeout(()=>d.remove(),2600);}
async function copyTo(url,label){try{const r=await fetch(url,{method:'POST'});if(!r.ok)throw 0;toast(label+'をコピーしました ✓');}catch{toast(label+'のコピーに失敗しました',true);}}

/* ================= 一覧 ================= */
let works=[], query='', openId=null, openSig='';
$('#refprof').onclick=e=>refreshProfiles(e.currentTarget);
function applySide(c){const t=$('#sidetg');$('#app').classList.toggle('collapsed',c);t.textContent=c?'▶':'◀';
  t.title=t.ariaLabel=c?'サイドバーを開く':'サイドバーを畳む';}
{let sv=null;try{sv=localStorage.getItem('sideCollapsed');}catch{}applySide(sv==null?innerWidth<1000:sv==='1');}
$('#sidetg').onclick=()=>{const c=!$('#app').classList.contains('collapsed');applySide(c);try{localStorage.setItem('sideCollapsed',c?'1':'0');}catch{}};
// Discordを開くボタン(Bot の接続が終わるまで、数秒おいて何度か確認する)
(function discordLink(n){api('/api/discord').then(r=>{if(r.url){const a=$('#discordbtn');a.href=r.url;a.hidden=false;}else if(n<8)setTimeout(()=>discordLink(n+1),2500);}).catch(()=>{});})(0);
api('/api/profiles').then(p=>setSync(p.length)).catch(()=>{$('#syncmeta').textContent='アカウント未取得';});
$('#q').addEventListener('input',e=>{query=e.target.value.trim().toLowerCase();render();});

const thumbOf=w=>{for(const p of w.posts){if(p.videos[0])return `/thumb/${p.id}/${p.videos[0]}`;if(p.images[0])return `/files/${p.id}/${p.images[0]}`;}return null;};
const countVideos=w=>w.posts.reduce((n,p)=>n+p.videos.length,0);
function matches(w){
  if(!query)return true;
  const hay=[...w.posts.map(p=>p.author+' '+p.text),...w.urls.map(u=>u.url)].join(' ').toLowerCase();
  return hay.includes(query);
}
// 占い用: 投稿の予定。予約があればその日時と状態、なければ計画の日時(未予約)
const STL={pending:'予約済み',running:'投稿中',done:'投稿済み',failed:'失敗',missed:'見送り'};
function planOf(w){
  const s=w.sched;
  if(s)return {t:s.at,label:STL[s.status]||s.status,cls:s.status};
  return w.planned_at?{t:w.planned_at,label:'未予約',cls:'plan'}:null;
}
function fortuneSec(w){
  const pl=planOf(w),t=(w.planned_at||'').slice(0,16);
  return `<section class="sec"><h3>投稿の予定</h3>
    <div class="note" style="margin:0 0 8px">${pl?`🕒 ${fmt(pl.t)}・${pl.label}`:'日時が未設定です'}</div>
    <div class="affrow"><input id="fplan" type="datetime-local" value="${esc(t)}" aria-label="投稿予定の日時"><button class="btn primary" id="fplansave">予定を保存</button></div>
    <div class="note">予定を保存しても、予約はまだ入りません(予約前の計画です)。予約済みの投稿の日時は、予約履歴で変更します。</div></section>
    ${(w.thread&&w.thread.length)?`<section class="sec"><h3>本文の続き(投稿の直後に、自分で返信して出ます)</h3>${w.thread.map((t,i)=>`<div class="note" style="margin:0 0 4px">続き${i+1}</div><div style="white-space:pre-wrap;margin-bottom:8px">${esc(t)}</div>`).join('')}</section>`:''}
    <section class="sec"><h3>続きのリプ(自動)</h3>
    <div class="note" style="margin:0 0 8px">この投稿が <b>表示2,500</b> か <b>いいね40</b> に届くと、同じアカウントから、次の順で自動でリプします。</div>
    <div class="note" style="margin:0 0 4px">① 1つ目のリプ(本文を、1投稿ごとに変えられます)</div>
    <textarea id="ftext" rows="5" style="width:100%" aria-label="1つ目のリプ">${esc(w.followup_text||'')}</textarea>
    <div class="note" style="margin:10px 0 4px">② 2つ目のリプ(リンク。計測用のコードを含むので、書き換えないでください)</div>
    <div class="affrow"><input id="faff" type="url" value="${esc(w.affiliate||'')}" aria-label="リプのリンク"><button class="btn" id="faffcopy">コピー</button></div>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="ftextsave">リプの内容を保存</button></div>
    <div class="note" id="fnote">広告表記(【PR】)を、1つ目のリプに必ず入れてください。届いていない間は、リプは出ません。</div></section>`;
}
const hasMedia=w=>w.posts.some(p=>p.videos.length||p.images.length);
const noAff=w=>!IS_ENT&&!(w.affiliate||'').trim();   // アダルト用: アフィリエイトリンク未登録
const wtOf=w=>noAff(w)?0:Math.max(0,w.weight==null?1:Number(w.weight)||0);  // 未登録は重み0(一括予約で選ばれない)
// 一括予約でこの作品が選ばれる確率(%)=この作品の重み ÷ 動画・画像のある全作品の重みの合計。エンタメ用・メディアなしは null
function pctOf(w){
  if(IS_ENT||IS_FORTUNE||!hasMedia(w))return null;
  const tot=works.filter(hasMedia).reduce((n,x)=>n+wtOf(x),0);
  return tot>0?wtOf(w)/tot*100:0;
}
const NOAFF_MSG='アフィリエイトリンクが未登録のため、一括予約では投稿されません(確率0%)。作品を開いてリンクを保存すると対象になります';
const fmtPct=v=>(v>=10||v===0?Math.round(v):Math.round(v*10)/10)+'%';
function render(){
  let list=works.filter(matches);
  if(!IS_ENT&&!IS_FORTUNE){  // 選ばれる確率が高い順(同じ確率なら従来どおり更新が新しい順)。動画・画像のない作品は最後
    const pc=new Map(list.map(w=>[w,pctOf(w)??-1]));
    list=list.sort((x,y)=>pc.get(y)-pc.get(x));
  }
  $('#count').textContent=`${list.length} / ${works.length} 作品`;
  $('#grid').innerHTML=list.length?list.map(w=>{
    const t=thumbOf(w),p=w.posts[0]||{},nv=countVideos(w),pc=pctOf(w),off=!IS_ENT&&wtOf(w)<=0,na=noAff(w);
    return `<button class="card${off?' off':''}" data-w="${esc(w.work_id)}"${off&&!na?' title="選ばれやすさ0: 一括予約の自動選択から外れています"':''}>
      <div class="thumb">${t?`<img src="${t}" loading="lazy" alt="">`:'<div class="none">メディアなし</div>'}
        ${na?`<span class="warn" title="${NOAFF_MSG}" aria-label="アフィリエイトリンク未登録">⚠</span>`:''}
        <div class="overlay">${nv?`<span class="pill">▶ 動画${nv}</span>`:''}${IS_FORTUNE?'':`<span class="pill">投稿${w.posts.length}</span>`}${(()=>{const pl=IS_FORTUNE?planOf(w):null;return pl?`<span class="pill plan ${pl.cls}" title="投稿予定">🕒 ${fmt(pl.t)}・${pl.label}</span>`:''})()}${pc==null?'':`<span class="pill pct" title="一括予約で選ばれる確率">🎲 ${fmtPct(pc)}</span>`}</div></div>
      <div class="body"><div class="author">${esc(p.author||'(投稿なし)')}</div>
        <div class="excerpt${IS_FORTUNE?' full':''}">${esc(p.text||'')}</div>
        <div class="foot">${[...new Set(w.urls.map(u=>u.site))].map(s=>`<span class="site ${s}">${s}</span>`).join('')}
          <span>更新 ${fmt(w.updated_at)}</span></div></div></button>`;}).join('')
    :`<div class="empty">${works.length?'条件に合う作品がありません':'まだ保存された作品がありません。Discord に X のリンクを送ってください。'}</div>`;
}
$('#grid').addEventListener('click',e=>{const c=e.target.closest('.card');if(c)openDrawer(c.dataset.w);});
const sig=w=>w?w.updated_at+'|'+w.posts.length+'|'+w.urls.length:'';
async function load(){
  try{works=await api('/api/items');}catch{return;}
  render();
  const w=works.find(x=>x.work_id===openId);
  if(openId&&$('#modal').hidden&&sig(w)!==openSig)drawDrawer(w);
}
setInterval(()=>{if($('#modal').hidden)load();},10000);

/* ================= 詳細ドロワー ================= */
let PROFILES=null;
const setLb=(b,txt)=>{const l=b.querySelector('.lb');if(l)l.textContent=txt;};
function setSync(n){const t=new Date().toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit'});$('#syncmeta').innerHTML=`${n}アカウント<br>最終同期 <b>${t}</b>`;}
async function refreshProfiles(btn){
  if(btn){btn.disabled=true;setLb(btn,'同期中…');}
  try{
    const old=PROFILES||await api('/api/profiles').catch(()=>[]);
    api('/api/avatars/refresh',{method:'POST'}).then(()=>setTimeout(async()=>{try{PROFILES=await api('/api/profiles');if(P&&P.step===0)renderPost();}catch(e){}},60000)).catch(()=>{});
    const nw=await api('/api/profiles');
    const key=a=>a.id+'|'+a.name+'|'+a.group, os=new Set(old.map(key));
    const changed=nw.filter(a=>!os.has(key(a))).length, gone=old.filter(a=>!nw.some(b=>b.id===a.id)).length;
    PROFILES=nw;setSync(nw.length);
    const gs=new Set(nw.map(a=>a.group)).size;
    toast(`同期しました: ${nw.length}アカウント / ${gs}グループ`+((PROFILES&&old.length&&(changed||gone))?`(変更${changed}・削除${gone})`:''));
    if(P&&P.step===0)renderPost();
  }catch(e){toast('同期に失敗: '+e.message,true);}
  finally{const b=$('#refprof');if(b){b.disabled=false;setLb(b,'Xdeckとアカウント同期');}
    const c=$('#pref');if(c){c.disabled=false;c.textContent='↻ 同期';}}
}
const avt=(p,s)=>p&&p.av?`<img class="av" src="/api/avatar/${p.id}?v=${p.av}" alt="" loading="lazy"${s?` style="width:${s}px;height:${s}px"`:''}>`:`<span class="av ph"${s?` style="width:${s}px;height:${s}px"`:''}>${esc((p&&p.name||'?').slice(0,1))}</span>`;
let avPoll=0;
function pollAvatars(){ // 未取得のアイコンは裏で取得中なので、数回だけ取り直して反映する
  if(avPoll>=8||!PROFILES||PROFILES.every(p=>p.av))return;
  avPoll++;
  setTimeout(async()=>{try{PROFILES=await api('/api/profiles');if(P&&P.step===0)renderPost();}catch(e){}pollAvatars();},20000);
}
async function profiles(){if(!PROFILES){PROFILES=await api('/api/profiles');pollAvatars();}return PROFILES;}
function openDrawer(id){openId=id;$('#scrim').hidden=false;$('#drawer').hidden=false;drawDrawer(works.find(w=>w.work_id===id));}
function closeDrawer(){openId=null;$('#scrim').hidden=true;$('#drawer').hidden=true;$('#drawer').innerHTML='';}
$('#scrim').addEventListener('click',()=>{if($('#modal').hidden)closeDrawer();});
async function drawDrawer(w){
  if(!w){closeDrawer();return;}
  openSig=sig(w);
  const d=$('#drawer');
  d.innerHTML=`<header><h2>作品の詳細</h2><span class="note" style="margin:0">作成 ${fmt(w.created_at)} ・ 更新 ${fmt(w.updated_at)}</span>
      <button class="iconbtn" id="dclose" aria-label="閉じる">✕</button></header>
    <div class="scroll">
      ${IS_FORTUNE?fortuneSec(w):''}
      ${IS_ENT||IS_FORTUNE?'':`<section class="sec"><h3>アフィリエイトリンク</h3>
        <div class="affrow"><input id="aff" type="url" inputmode="url" placeholder="MyFansで作成したURLを貼り付け" value="${esc(w.affiliate||'')}" aria-label="アフィリエイトリンク">
          <button class="btn primary" id="affsave">保存</button><button class="btn" id="affcopy" ${w.affiliate?'':'disabled'}>コピー</button></div>
        <div class="row" style="margin-top:8px"><button class="btn primary" id="affopen">↗ MyFansアフィリンクを作成</button></div>
        <div class="note" id="affnote">${w.affiliate?'':'「MyFansアフィリンクを作成」を押すと作成ページが開きます。できたリンクをここに貼り付けて「保存」を押してください。'}</div></section>`}
      ${IS_ENT||IS_FORTUNE?'':`<section class="sec"><h3>選ばれやすさ(一括予約のランダム選択)</h3>
        <div class="affrow"><input id="wt" type="number" min="0" max="10" step="0.5" value="${w.weight==null?1:w.weight}" style="max-width:110px" aria-label="選ばれやすさ">
          <button class="btn primary" id="wtsave">保存</button></div>
        <div class="note" id="wtnote">${noAff(w)?'⚠ '+NOAFF_MSG+'。':''}標準=1 / 2にすると標準の2倍選ばれやすい / 0.5で半分 / 0で自動選択から外す(0〜10)。作品ごとの確率は「この作品の重み ÷ 全作品の重みの合計」です。</div></section>`}
      ${IS_FORTUNE?'':`<section class="sec"><h3>作品URL</h3>${w.urls.length?w.urls.map(u=>`<div class="urlrow"><span class="site ${u.site}">${u.site}</span>
        <a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.url)}</a>
        <button class="btn sm" data-copyurl="${esc(u.url)}">コピー</button><span class="note" style="margin:0">${fmt(u.added_at)}</span></div>`).join('')
        :'<div class="note">スレッドに MyFans / FANZA の URL を送ると、ここに表示されます。</div>'}</section>`}
      <section class="sec"><h3>保存した投稿(${w.posts.length}件)</h3>${w.posts.map(p=>`<div class="post">
        <div class="meta"><b>${esc(p.author)}</b><span>🕒 保存 ${fmt(p.saved_at)}</span><a href="${esc(p.url)}" target="_blank" rel="noopener" style="color:#8ecdf8;font-size:12px">元の投稿</a>
          ${p.discord&&p.discord.url?`<a href="${esc(p.discord.url)}" target="_blank" rel="noopener" style="color:#8ecdf8;font-size:12px">Discordで開く${p.discord.thread?'('+esc(p.discord.thread)+')':''}</a>`:''}
          ${w.posts.length>1?`<button class="btn sm" data-split="${esc(p.id)}">✂ 別の作品に分ける</button>`:''}</div>
        <div class="text">${esc(p.text)}</div>
        ${p.videos.map(v=>`<video src="/files/${p.id}/${v}" controls preload="metadata"></video>
          <div class="actions"><button class="btn sm" data-copy="/copy/${p.id}/${v}" data-label="動画">🎬 動画をコピー</button></div>`).join('')}
        ${p.images.map(m=>`<img class="full" src="/files/${p.id}/${m}" loading="lazy" alt="">
          <div class="actions"><button class="btn sm" data-copy="/copy/${p.id}/${m}" data-label="画像">🖼 画像をコピー</button></div>`).join('')}
        <div class="actions"><button class="btn sm" data-copy="/copytext/${p.id}" data-label="本文">📝 本文をコピー</button></div></div>`).join('')}</section>
      <section class="sec"><h3>投稿履歴</h3><div id="hist" class="note">読み込み中…</div></section>
      <section class="sec"><button class="btn danger" id="delwork">🗑 この作品を削除</button></section>
    </div>
    <footer><button class="btn primary block" id="dpost">📤 この作品を X に投稿する</button></footer>`;
  $('#dclose').onclick=closeDrawer;
  $('#dpost').onclick=()=>openPost(w);
  $('#delwork').onclick=async()=>{
    const n=w.posts.length;
    if(!confirm(`この作品(保存した投稿${n}件)を削除しますか?\n\n・ボードから消えます\n・ファイルは data/保存先/state/_trash/ に移動されます(完全には削除されません)\n・予約投稿が入っている場合は、予約一覧から別に取り消してください`))return;
    try{await api('/api/delete_work',{method:'POST',body:JSON.stringify({work_id:w.work_id})});closeDrawer();await load();toast('作品を削除しました(_trash に移動)');}
    catch(e){toast('削除に失敗: '+e.message,true);}
  };
  if(IS_FORTUNE){
    $('#fplansave').onclick=async()=>{
      const v=$('#fplan').value;
      if(!v){toast('日時を入れてください',true);return;}
      try{const r=await api('/api/fortune/plan',{method:'POST',body:JSON.stringify({work_id:w.work_id,planned_at:v})});w.planned_at=r.planned_at;render();toast('予定を保存しました ✓(予約はまだです)');}
      catch(e){toast('保存に失敗: '+e.message,true);}
    };
    $('#ftextsave').onclick=async()=>{
      const text=$('#ftext').value.trim(),url=$('#faff').value.trim();
      try{
        await api('/api/fortune/plan',{method:'POST',body:JSON.stringify({work_id:w.work_id,followup_text:text})});
        const r=await api('/api/affiliate',{method:'POST',body:JSON.stringify({work_id:w.work_id,url})});
        w.followup_text=text;w.affiliate=r.affiliate;$('#fnote').textContent='保存しました ✓';toast('リプの内容を保存しました ✓');
      }catch(e){toast('保存に失敗: '+e.message,true);}
    };
    $('#faffcopy').onclick=()=>{navigator.clipboard.writeText($('#faff').value).then(()=>toast('リンクをコピーしました ✓'),()=>toast('コピーに失敗しました',true));};
  }
  const wt=$('#wt');
  if(wt){
    const wsave=async()=>{
      const v=Number(wt.value);
      if(!(v>=0&&v<=10)){toast('0〜10の数値を入れてください',true);return;}
      try{
        const r=await api('/api/weight',{method:'POST',body:JSON.stringify({work_id:w.work_id,weight:v})});
        w.weight=r.weight;render();$('#wtnote').textContent='保存しました ✓(この作品が選ばれる確率: '+(noAff(w)?'0%(アフィリエイトリンク未登録)':pctOf(w)==null?'対象外(動画・画像なし)':fmtPct(pctOf(w)))+')';toast('選ばれやすさを保存しました ✓');
      }catch(e){toast('保存に失敗: '+e.message,true);}
    };
    $('#wtsave').onclick=wsave;
    wt.addEventListener('keydown',e=>{if(e.key==='Enter')wsave();});
  }
  const aff=$('#aff');
  if(aff){
    const note=$('#affnote'),cp=$('#affcopy');
    const save=async()=>{
      const v=aff.value.trim();
      try{
        const r=await api('/api/affiliate',{method:'POST',body:JSON.stringify({work_id:w.work_id,url:v})});
        w.affiliate=r.affiliate;cp.disabled=!r.affiliate;render();
        note.textContent=r.affiliate?'保存しました ✓':'削除しました';toast(r.affiliate?'アフィリエイトリンクを保存しました ✓':'アフィリエイトリンクを削除しました');
      }catch(e){note.textContent='保存に失敗: '+e.message;toast('保存に失敗: '+e.message,true);}
    };
    $('#affsave').onclick=save;
    $('#affopen').onclick=async()=>{
      const mf=(w.urls||[]).find(u=>u.site==='MyFans');
      if(mf){
        try{const r=await fetch(`/copyurl/${w.work_id}/${encodeURIComponent(mf.url)}`,{method:'POST'});if(!r.ok)throw 0;toast('作品URLをコピーしました。作成ページに貼り付けてください ✓');}
        catch{toast('作品URLのコピーに失敗しました',true);}
      }else toast('この作品にはMyFansのURLがありません(作成ページだけ開きます)');
      window.open('https://www.affiliate.myfans.jp/affiliates/url','_blank','noopener');};
    aff.addEventListener('keydown',e=>{if(e.key==='Enter')save();});
    cp.onclick=async()=>{try{await navigator.clipboard.writeText(w.affiliate);toast('アフィリエイトリンクをコピーしました ✓');}catch{toast('コピーに失敗しました',true);}};
  }
  d.onclick=e=>{const b=e.target.closest('button');if(!b)return;
    if(b.dataset.copy)copyTo(b.dataset.copy,b.dataset.label);
    if(b.dataset.copyurl)copyTo(`/copyurl/${w.work_id}/${encodeURIComponent(b.dataset.copyurl)}`,'URL');
    if(b.dataset.split&&confirm('この投稿を、いまの作品から切り離して別の作品にしますか?'))
      api('/api/move',{method:'POST',body:JSON.stringify({id:b.dataset.split,to:''})}).then(async()=>{closeDrawer();await load();toast('別の作品に分けました ✓');}).catch(e=>toast('失敗: '+e.message,true));};
  try{
    const [h,ps]=await Promise.all([api('/api/history/'+w.work_id),profiles().catch(()=>[])]);
    const nm=id=>(ps.find(p=>p.id===id)||{}).name||id.slice(0,8);
    const el=$('#hist');if(el)el.innerHTML=h.length?h.map(x=>`<div class="hist"><div class="t">${fmt(x.at)} ・ ${esc(nm(x.profile_id))}</div>${esc(x.text.slice(0,80))}${x.text.length>80?'…':''}</div>`).join(''):'まだ投稿していません';
  }catch{const el=$('#hist');if(el)el.textContent='履歴を読み込めませんでした';}
}

/* ================= 投稿シート ================= */
const DEF={crop:[2,2],br:[0.02,0.08],ct:[1.05,1.15],sa:[1.15,1.15],trim:[0.1,0.5]};
let P=null;
const STEPS=['アカウント','本文','動画','確認と投稿'];
const isVid=n=>n.endsWith('.mp4');
function mediaOf(w){const out=[];for(const p of w.posts){for(const v of p.videos)out.push({id:p.id,name:v,k:'v'});for(const m of p.images)out.push({id:p.id,name:m,k:'i'});}return out;}
const keyOf=m=>m.id+'/'+m.name;

function openPost(w){
  const media=mediaOf(w),vids=media.filter(m=>m.k==='v');
  const text0=((w.posts[0]||{}).text||'').replace(/\s*https?:\/\/\S+/g,'').trim();
  P={w,step:0,profile:'',profName:'',accQ:'',text:text0,orig:text0,rw:'idle',cands:[],media,sel:vids.length?[vids[Math.floor(Math.random()*vids.length)]]:[],
     useEd:true,ed:{state:'idle'},edTok:0,params:structuredClone(DEF),post:{state:'idle'},when:'now',at:defAt()};
  $('#modal').hidden=false;
  profiles().then(()=>{if(P&&P.step===0)renderPost();}).catch(e=>toast('アカウント一覧を取得できません: '+e.message,true));
  runRewrite();runEdit();renderPost();
}
function closePost(){P=null;$('#modal').hidden=true;$('#modal').innerHTML='';load();}

async function runRewrite(){
  const p=P;p.rw='busy';upd();
  try{const o=await api('/api/rewrite',{method:'POST',body:JSON.stringify({text:p.orig})});
    if(P!==p)return;p.cands=o.candidates||[o.text];if(p.text===p.orig||p.rwForce)p.text=p.cands[0];p.rwForce=false;p.rw='ok';}
  catch(e){if(P!==p)return;p.rw='err';p.rwErr=e.message;}
  upd();
}
function paramBody(){const q=P.params;return {crop_a:q.crop[0]/100,crop_b:q.crop[1]/100,br_a:q.br[0],br_b:q.br[1],ct_a:q.ct[0],ct_b:q.ct[1],sa_a:q.sa[0],sa_b:q.sa[1],trim_min:q.trim[0],trim_max:q.trim[1]};}
async function runEdit(){
  const p=P,vid=p.sel.find(m=>m.k==='v');
  if(!vid||!p.useEd){p.ed={state:'idle'};upd();return;}
  const tok=++p.edTok;p.ed={state:'busy'};upd();
  try{const o=await api('/api/edit',{method:'POST',body:JSON.stringify({id:vid.id,name:vid.name,...paramBody()})});
    if(P!==p||tok!==p.edTok)return;p.ed={state:'ok',key:keyOf(vid),info:o};}
  catch(e){if(P!==p||tok!==p.edTok)return;p.ed={state:'err',err:e.message};}
  upd();
}
function upd(){if(P)renderPost(true);}

function stepDone(i){
  if(i===0)return !!P.profile;
  if(i===1)return !!P.text.trim();
  if(i===2)return !P.sel.some(m=>m.k==='v')||!P.useEd||P.ed.state==='ok';
  return false;
}
function badge(kind,txt){return `<span class="status ${kind}">${kind==='busy'?'<span class="spin"></span>':kind==='ok'?'✓':kind==='err'?'!':''}${txt}</span>`;}

function renderPost(keepFocus){
  if(!P)return;
  const ae=document.activeElement,ta=ae&&ae.tagName==='TEXTAREA'?ae:null,selStart=ta?ta.selectionStart:0;
  const m=$('#modal');
  m.innerHTML=`<div class="sheet">
    <header><h2>投稿を作成</h2><button class="iconbtn" id="pclose" aria-label="閉じる">✕</button></header>
    <nav class="steps">${STEPS.map((s,i)=>`<button data-s="${i}" class="${i!==P.step&&stepDone(i)?'done':''}" ${i===P.step?'aria-current="step"':''}><span class="n">${i!==P.step&&stepDone(i)?'✓':i+1}</span>${s}</button>`).join('')}</nav>
    <div class="content">${[stepAcc,stepText,stepMedia,stepConfirm][P.step]()}</div>
    ${P.post.state==='ok'?'':`<footer>
      <button class="btn" id="pback" ${P.step===0?'disabled':''}>← 戻る</button>
      ${P.step<3?`<button class="btn primary" id="pnext">次へ →</button>`:''}</footer>`}
  </div>`;
  bindPost();
  if(ta&&keepFocus){const t=$('#ptext');if(t){t.focus();t.setSelectionRange(selStart,selStart);}}
}

function stepAcc(){
  const ps=PROFILES||[],q=P.accQ.toLowerCase();
  const list=ps.filter(p=>!q||p.name.toLowerCase().includes(q)||p.group.includes(q));
  const groups=[...new Set(list.map(p=>p.group))];
  return `<div class="field"><div class="row" style="justify-content:space-between;margin-bottom:6px"><label class="l" for="paccq" style="margin:0">投稿するアカウント</label><button class="btn" id="pref" style="padding:4px 10px" title="Xdeckのアカウント情報と同期する">↻ 同期</button></div>
    <input id="paccq" type="text" placeholder="名前・グループで絞り込み" value="${esc(P.accQ)}"></div>
    ${!PROFILES?'<div class="note">アカウント一覧を読み込み中…</div>':`<div class="accs" role="radiogroup" aria-label="アカウント">${groups.map(g=>`<div class="grp">${esc(g)}</div>${list.filter(p=>p.group===g).map(p=>`<button class="acc" role="radio" aria-checked="${P.profile===p.id}" data-p="${p.id}"><span class="mark"></span>${avt(p)}${esc(p.name)} ${sbBadge(p)}<span class="lastp">${esc(lastTxt(p))}</span></button>`).join('')}`).join('')||'<div class="note" style="padding:12px">該当なし</div>'}</div>`}
    <div class="note">${P.profile?`選択中: <b>${esc(P.profName)}</b>`:'アカウントを選んでください'}</div>`;
}
function stepText(){
  return `<div class="field"><div class="row" style="justify-content:space-between;margin-bottom:6px"><label class="l" for="ptext" style="margin:0">本文</label>
      <div class="row">${P.rw==='busy'?badge('busy','リライト中'):P.rw==='ok'?badge('ok','リライト済み'):P.rw==='err'?badge('err','リライト失敗(元の文のまま)'):''}</div></div>
    <textarea id="ptext">${esc(P.text)}</textarea>
    <div class="row" style="margin-top:8px"><button class="btn sm" id="prw" ${P.rw==='busy'?'disabled':''}>✨ リライトをやり直す</button>
      <button class="btn sm" id="prestore">↩ 元の文に戻す</button><span class="note" style="margin-left:auto">${[...P.text].length} 文字</span></div>
    ${P.rw==='err'?`<div class="note" style="color:var(--err)">${esc(P.rwErr||'')}</div>`:''}
    ${P.cands.length?`<div class="field" style="margin-top:14px"><label class="l">リライト案(押すと本文に入ります)</label>
      ${P.cands.map((c,i)=>`<button class="cand" data-c="${i}" aria-pressed="${P.text===c}"><b>案${i+1}</b> ${esc(c.replace(/\s*https?:\/\/\S+/g,''))}</button>`).join('')}</div>`:''}</div>
    <div class="note">リライト結果は自由に編集できます。内容は次の「確認と投稿」で最終確認します。</div>`;
}
function stepMedia(){
  const rg=(k,l,step,min,max)=>`<div>${l}</div><input class="num" type="number" step="${step}" min="${min}" max="${max}" data-r="${k}" data-i="0" value="${P.params[k][0]}"><input class="num" type="number" step="${step}" min="${min}" max="${max}" data-r="${k}" data-i="1" value="${P.params[k][1]}">`;
  const vid=P.sel.find(m=>m.k==='v');
  return `<div class="field"><label class="l">添付するメディア(動画は1本、または画像を最大4枚)</label>
    ${P.media.length?`<div class="tiles">${P.media.map(m=>`<button class="tile" data-m="${esc(keyOf(m))}" aria-pressed="${P.sel.some(s=>keyOf(s)===keyOf(m))}">
      <img src="${m.k==='v'?'/thumb/':'/files/'}${m.id}/${m.name}" alt=""><span class="lab">${m.k==='v'?'🎬 動画':'🖼 画像'} ・ ${esc(m.name)}</span></button>`).join('')}</div>`:'<div class="note">この作品にはメディアがありません(本文のみ投稿されます)</div>'}
    ${P.media.filter(m=>m.k==='v').length>1?`<div class="row" style="margin-top:10px"><button class="btn sm" id="pdice">🎲 別の動画をランダムで選ぶ</button></div>`:''}</div>
  ${vid?`<div class="field"><div class="row" style="justify-content:space-between"><label class="row" style="gap:8px"><input type="checkbox" id="puse" ${P.useEd?'checked':''}> 動画を加工する(色味・切り抜き・前後カット)</label>
      <div class="row">${P.useEd?(P.ed.state==='busy'?badge('busy','加工中(数十秒かかります)'):P.ed.state==='ok'?badge('ok','加工済み'):P.ed.state==='err'?badge('err','加工失敗'):''):badge('', '加工なし')}</div></div>
    ${P.ed.state==='err'?`<div class="note" style="color:var(--err)">${esc(P.ed.err)}</div>`:''}
    ${P.useEd&&P.ed.state==='ok'?`<video src="${P.ed.info.url}" preload="metadata" controls style="width:100%;max-height:300px;background:#000;border-radius:10px;margin-top:10px"></video>
      <div class="note">先頭 ${P.ed.info.head}秒・末尾 ${P.ed.info.tail}秒カット ／ 切り抜き ${(P.ed.info.crop*100).toFixed(1)}% ／ 明るさ ${P.ed.info.brightness} ／ コントラスト ${P.ed.info.contrast} ／ 彩度 ${P.ed.info.saturation}</div>`:''}
    <div class="row" style="margin-top:10px"><button class="btn sm" id="predo" ${P.ed.state==='busy'?'disabled':''}>🎞 加工をやり直す</button></div>
    <details style="margin-top:12px"><summary>加工の詳細設定(毎回、範囲内でランダムに決まります)</summary>
      <div class="rng"><div></div><div class="note">最小</div><div class="note">最大</div>
      ${rg('crop','切り抜き(四辺・%)',0.5,0,10)}${rg('br','明るさ',0.01,-0.3,0.3)}${rg('ct','コントラスト',0.05,0.5,2)}${rg('sa','彩度',0.05,0,3)}${rg('trim','前後カット(秒)',0.1,0,2)}</div></details></div>`:''}`;
}
function blockers(){
  const b=[];
  if(!P.profile)b.push('アカウントが未選択です');
  if(!P.text.trim())b.push('本文が空です');
  const hasV=P.sel.some(m=>m.k==='v');
  if(hasV&&P.useEd&&P.ed.state==='busy')b.push('動画を加工しています。完了までお待ちください');
  if(hasV&&P.useEd&&P.ed.state==='err')b.push('動画の加工に失敗しました。やり直すか、「加工する」を外してください');
  if(hasV&&P.useEd&&P.ed.state==='idle')b.push('動画が未加工です');
  return b;
}
const SBI={ok:['🟢','問題なし'],warn:['🟡','注意'],bad:['🔴','規制の疑い'],unknown:['⚪','判定不能']};
function sbBadge(p){if(!p.sb)return '<span class="sbb" title="未判定">⚫</span>';const i=SBI[p.sb.level]||SBI.unknown;
  const tip=`${p.sb.label}${p.sb.flags&&p.sb.flags.length?'('+p.sb.flags.join('・')+')':''} ${p.sb.checked_at.slice(5,16).replace('T',' ')}${p.sb.error?' '+p.sb.error:''}`;
  return `<span class="sbb" title="${esc(tip)}">${i[0]}</span><span class="sbt">${esc(p.sb.label)}${p.sb.flags&&p.sb.flags.length?`:${esc(p.sb.flags.join("・"))}`:p.sb.error?`:${esc(p.sb.error)}`:''}</span>`;}
function lastTxt(p){const l=p.last?`前回 ${fmtAt(p.last).slice(5)}`:'前回 なし';
  return p.next?`${l} ／ 予約 ${fmtAt(p.next).slice(5)}${p.next_n>1?`(他${p.next_n-1}件)`:''}`:l;}
function impTxt(p){const i=p.imp;return !p.has_post?'imp -':!i||i.views==null?'imp 未取得':`📈 ${Number(i.views).toLocaleString()} imp`;}
function pad(n){return String(n).padStart(2,'0');}
function toLocalInput(d){return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;}
function defAt(){const d=new Date(Date.now()+3600e3);d.setMinutes(0,0,0);return toLocalInput(d);}
function fmtAt(s){const d=new Date(s);return `${d.getFullYear()}/${pad(d.getMonth()+1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;}
function stepConfirm(){
  const po=P.post;
  if(po.state==='ok')return `<div class="result"><div style="font-size:42px">✅</div><h3>投稿しました</h3>
    <div class="note">${esc(P.profName)} ${po.link?'':'(投稿IDの取得はできませんでした)'}</div>
    ${po.imp?`<div class="note">🔔 ${po.imp.toLocaleString()}インプに達したら Discord に通知します</div>`:''}
    <div class="row" style="justify-content:center;margin-top:16px">${po.link?`<a class="btn primary" href="${esc(po.link)}" target="_blank" rel="noopener">X で投稿を開く</a>`:''}
      <button class="btn" id="pagain">別のアカウントで投稿する</button><button class="btn" id="pclose2">閉じる</button></div></div>`;
  if(po.state==='sched')return `<div class="result"><div style="font-size:42px">🕒</div><h3>予約しました</h3>
    <div class="note">${esc(P.profName)} / ${esc(fmtAt(po.at))} に投稿します<br>※ この時刻に Bot(このMac)が起動している必要があります</div>
    <div class="row" style="justify-content:center;margin-top:16px"><button class="btn primary" id="pshowsched">予約一覧を見る</button>
      <button class="btn" id="pagain">別のアカウントで投稿する</button><button class="btn" id="pclose2">閉じる</button></div></div>`;
  const vid=P.sel.find(m=>m.k==='v'),imgs=P.sel.filter(m=>m.k==='i'),bl=blockers();
  const mediaHtml=vid?(P.useEd&&P.ed.state==='ok'?`<video src="${P.ed.info.url}" preload="metadata" controls></video>`:`<video src="/files/${vid.id}/${vid.name}" controls></video>`):imgs.map(m=>`<img src="/files/${m.id}/${m.name}" alt="">`).join('');
  return `<div class="preview"><div class="who"><div class="avatar">${(()=>{const pp=(PROFILES||[]).find(q=>q.id===P.profile);return pp&&pp.av?`<img src="/api/avatar/${pp.id}?v=${pp.av}" alt="" style="width:100%;height:100%;object-fit:cover;margin:0;border-radius:0;max-height:none">`:esc((P.profName||'?').slice(0,1));})()}</div><div><b>${esc(P.profName||'(アカウント未選択)')}</b><div class="note" style="margin:0">投稿プレビュー</div></div></div>
    <div class="tx">${esc(P.text)}</div>${mediaHtml}</div>
    <ul class="checks"><li class="${P.profile?'':'ng'}">投稿先: ${esc(P.profName||'未選択')}</li>
      <li class="${P.text.trim()?'':'ng'}">本文 ${[...P.text].length} 文字</li>
      <li>添付: ${vid?(P.useEd?'動画1本(加工版)':'動画1本(未加工)'):imgs.length?`画像${imgs.length}枚`:'なし'}</li></ul>
    ${bl.map(x=>`<div class="note" style="color:var(--warn)">! ${esc(x)}</div>`).join('')}
    ${po.state==='err'?`<div class="note" style="color:var(--err)">投稿に失敗しました: ${esc(po.err)}</div>`:''}
    <div class="field" style="margin-top:14px"><div class="l">投稿のタイミング</div>
      <div class="row"><label><input type="radio" name="pwhen" value="now" ${P.when==='now'?'checked':''}> 今すぐ</label>
      <label><input type="radio" name="pwhen" value="sched" ${P.when==='sched'?'checked':''}> 日時を指定して予約</label>
      ${P.when==='sched'?`<input type="datetime-local" id="pat" value="${esc(P.at)}" step="60">`:''}</div></div>
    <div style="margin-top:16px"><button class="btn go block" id="psubmit" ${bl.length||po.state==='busy'?'disabled':''}>${po.state==='busy'?(P.when==='sched'?'予約中…':'投稿中…(最大1分ほどかかります)'):P.when==='sched'?`「${esc(P.profName||'アカウント')}」で予約する`:`「${esc(P.profName||'アカウント')}」で投稿する`}</button>
    <div class="note" style="text-align:center">${P.when==='sched'?'指定した時刻に自動で X へ公開されます(それまでは予約一覧から取り消せます)':'このボタンを押すと、すぐに X へ公開されます'}</div></div>`;
}

function bindPost(){
  const m=$('#modal');
  $('#pclose').onclick=closePost;
  const pr=$('#pref');if(pr)pr.onclick=()=>{pr.disabled=true;pr.textContent='同期中…';refreshProfiles(null);};
  const pc2=$('#pclose2');if(pc2)pc2.onclick=closePost;
  m.querySelectorAll('.steps button').forEach(b=>b.onclick=()=>{P.step=+b.dataset.s;renderPost();});
  const nx=$('#pnext');if(nx)nx.onclick=()=>{P.step++;renderPost();};
  const bk=$('#pback');if(bk)bk.onclick=()=>{P.step--;renderPost();};
  const aq=$('#paccq');if(aq)aq.oninput=e=>{P.accQ=e.target.value;const pos=e.target.selectionStart;renderPost();const n=$('#paccq');n.focus();n.setSelectionRange(pos,pos);};
  m.querySelectorAll('.acc').forEach(b=>b.onclick=()=>{P.profile=b.dataset.p;P.profName=(PROFILES.find(p=>p.id===b.dataset.p)||{}).name||'';renderPost();});
  const t=$('#ptext');if(t)t.oninput=e=>{P.text=e.target.value;};
  const rw=$('#prw');if(rw)rw.onclick=()=>{P.rwForce=true;runRewrite();};
  m.querySelectorAll('.cand').forEach(b=>b.onclick=()=>{P.text=P.cands[+b.dataset.c];renderPost();});
  const rs=$('#prestore');if(rs)rs.onclick=()=>{P.text=P.orig;renderPost();};
  m.querySelectorAll('.tile').forEach(b=>b.onclick=()=>{
    const mm=P.media.find(x=>keyOf(x)===b.dataset.m),on=P.sel.some(s=>keyOf(s)===b.dataset.m);
    if(mm.k==='v'){P.sel=[mm];runEdit();}
    else{P.sel=P.sel.filter(s=>s.k==='i');if(on)P.sel=P.sel.filter(s=>keyOf(s)!==b.dataset.m);else if(P.sel.length<4)P.sel.push(mm);else toast('画像は最大4枚です',true);}
    renderPost();});
  const dice=$('#pdice');if(dice)dice.onclick=()=>{const v=P.media.filter(x=>x.k==='v'&&keyOf(x)!==keyOf(P.sel[0]||{}));P.sel=[v[Math.floor(Math.random()*v.length)]];runEdit();renderPost();};
  const use=$('#puse');if(use)use.onchange=e=>{P.useEd=e.target.checked;if(P.useEd)runEdit();else{P.ed={state:'idle'};renderPost();}};
  const rd=$('#predo');if(rd)rd.onclick=()=>runEdit();
  m.querySelectorAll('[data-r]').forEach(i=>i.onchange=e=>{P.params[i.dataset.r][+i.dataset.i]=+e.target.value;});
  const ag=$('#pagain');if(ag)ag.onclick=()=>{P.post={state:'idle'};P.step=0;P.profile='';P.profName='';renderPost();};
  m.querySelectorAll('input[name=pwhen]').forEach(r=>r.onchange=()=>{P.when=r.value;renderPost();});
  const pa=$('#pat');if(pa)pa.onchange=e=>{P.at=e.target.value;renderPost();};
  const ps=$('#pshowsched');if(ps)ps.onclick=()=>{closePost();openSched();};
  const sb=$('#psubmit');if(sb)sb.onclick=submitPost;
}

async function submitPost(){
  const p=P;if(blockers().length||p.post.state==='busy')return;
  p.post={state:'busy'};renderPost();
  const vid=p.sel.find(m=>m.k==='v');
  const files=vid?[{id:vid.id,name:vid.name,edited:p.useEd}]:p.sel.map(m=>({id:m.id,name:m.name,edited:false}));
  if(p.when==='sched'){
    try{
      if(!p.at||new Date(p.at)<=new Date())throw new Error('予約日時は現在より後にしてください');
      await api('/api/schedule',{method:'POST',body:JSON.stringify({work_id:p.w.work_id,profile_id:p.profile,text:p.text.trim(),files,at:p.at})});
      if(P!==p)return;p.post={state:'sched',at:p.at};refreshSchedCount();
    }catch(e){if(P!==p)return;p.post={state:'err',err:e.message};}
    renderPost();return;
  }
  try{
    const o=await api('/api/post',{method:'POST',body:JSON.stringify({work_id:p.w.work_id,profile_id:p.profile,text:p.text.trim(),files})});
    if(o.code!==0)throw new Error(o.msg||JSON.stringify(o));
    const d=o.data||{},jid=d.job_id||d.id||d.jobId;let job=null;
    for(let i=0;jid&&i<40;i++){
      job=(await api('/api/job/'+jid).catch(()=>({}))).data||null;
      if(job&&['done','failed','error','finished','completed'].includes(String(job.state).toLowerCase()))break;
      await new Promise(r=>setTimeout(r,2000));
    }
    if(P!==p)return;
    if(job&&(job.failed>0||job.state==='failed'||job.state==='error'))throw new Error((job.error)||'Xdeck 側で投稿に失敗しました');
    const label=((job&&job.steps&&job.steps[0]||{}).label||'').replace('@',''),tid=job&&job.tweet_id;
    p.post={state:'ok',link:label&&tid?`https://x.com/${label}/status/${tid}`:''};
    if(p.post.link)api('/api/imp_alert',{method:'POST',body:JSON.stringify({url:p.post.link})}).then(r=>{if(P===p){p.post.imp=r.ok?r.target:0;renderPost();}}).catch(()=>{});
  }catch(e){if(P!==p)return;p.post={state:'err',err:e.message};}
  renderPost();
}

/* ===== 一括予約 ===== */
let BK=null;
async function openFortuneBulk(){
  // 占い用: 準備完了の投稿案を、それぞれに設定した日時で予約する
  const pn=$('#bulkpanel');pn.hidden=false;
  const draw=(inner)=>{pn.innerHTML=`<div class="sheet"><header><h2>一括予約投稿(占い)</h2><button class="iconbtn" id="bclose" aria-label="閉じる">✕</button></header><div class="content">${inner}</div></div>`;$('#bclose').onclick=()=>{pn.hidden=true;pn.innerHTML='';};};
  draw('<div class="note">確認中…</div>');
  let r;try{r=await api('/api/fortune/schedule_all',{method:'POST',body:JSON.stringify({dry:true})});}catch(e){draw(`<div class="note">${esc(e.message)}</div>`);return;}
  const ok=r.items.filter(x=>x.ok),ng=r.items.filter(x=>!x.ok);
  draw(`<div class="note" style="margin-bottom:10px">各投稿案に設定した日時で、<b>${esc(r.profile)}</b> から予約します。続きのリプや、2,500表示後の自動リプも、そのまま働きます。</div>
    ${ok.map(x=>`<div class="note" style="margin:0 0 4px">🕒 ${fmt(x.at)}　${esc(x.text)}</div>`).join('')||'<div class="note">予約できる投稿案がありません</div>'}
    ${ng.length?`<div class="note" style="margin-top:10px">対象外 ${ng.length}件: ${ng.map(x=>esc(x.reason)).filter((v,i,a)=>a.indexOf(v)===i).join('、')}</div>`:''}
    <div style="margin-top:14px"><button class="btn go block" id="fbrun" ${ok.length?'':'disabled'}>${ok.length}件を予約する</button></div><div class="note" id="fbnote"></div>`);
  $('#fbrun').onclick=async()=>{
    $('#fbrun').disabled=true;
    try{const o=await api('/api/fortune/schedule_all',{method:'POST',body:JSON.stringify({})});$('#fbnote').textContent=`${o.made}件を予約しました ✓(予約履歴で確認できます)`;toast(`${o.made}件を予約しました ✓`);if(typeof load==='function')load();}
    catch(e){$('#fbnote').textContent='失敗: '+e.message;$('#fbrun').disabled=false;}
  };
}
async function openBulk(){
  if(IS_FORTUNE)return openFortuneBulk();
  // 投稿する時間帯の初期値: 開始=今の時刻、終了=その2時間後(日をまたぐ場合は終了日も翌日)
  const t=new Date(),e=new Date(t.getTime()+2*3600e3);
  BK={sel:new Set(),q:'',sd:ymd(t),st:hm(t),ed:ymd(e),et:hm(e),per:1,state:'form',preset:''};
  $('#bulkpanel').hidden=false;drawBulk();
  try{await profiles();}catch(e){toast('アカウント一覧を取得できません: '+e.message,true);}
  if(BK)drawBulk();
}
const WD='日月火水木金土';
function ymd(d){return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;}
function hm(d){return `${pad(d.getHours())}:${pad(d.getMinutes())}`;}
function dayOpts(){const o=[],n=new Date();for(let i=0;i<15;i++){const d=new Date(n.getFullYear(),n.getMonth(),n.getDate()+i);
  o.push({v:ymd(d),l:`${d.getMonth()+1}/${d.getDate()}(${WD[d.getDay()]})${i===0?' 今日':i===1?' 明日':i===2?' 明後日':''}`});}return o;}
const TIMES=Array.from({length:48},(_,i)=>`${pad(i>>1)}:${i%2?'30':'00'}`);
const BPRE=[['朝','06:00','10:00'],['昼','11:00','14:00'],['夕方','17:00','20:00'],['夜','20:00','24:00'],['終日','08:00','23:30']];
const bStart=B=>`${B.sd}T${B.st}`,bEnd=B=>`${B.ed}T${B.et}`;
function applyPre(B,pre){B.preset=pre[0];B.st=pre[1];B.ed=B.sd;
  if(pre[2]==='24:00'){B.et='00:00';const d=new Date(B.sd+'T00:00');d.setDate(d.getDate()+1);B.ed=ymd(d);}else B.et=pre[2];}
function dsel(id,val){return `<select id="${id}" class="tsel">${dayOpts().map(o=>`<option value="${o.v}" ${o.v===val?'selected':''}>${o.l}</option>`).join('')}</select>`;}
function tsel(id,val){const ts=TIMES.includes(val)?TIMES:[...TIMES,val].sort();return `<select id="${id}" class="tsel">${ts.map(t=>`<option ${t===val?'selected':''}>${t}</option>`).join('')}</select>`;}
function bSummary(B){const a=new Date(bStart(B)),b=new Date(bEnd(B)),mins=(b-a)/6e4;
  if(!(mins>0))return '⚠ 終了は開始より後にしてください';
  const f=d=>`${d.getMonth()+1}/${d.getDate()}(${WD[d.getDay()]}) ${hm(d)}`;
  return `${f(a)} 〜 ${f(b)}(${mins>=60?Math.floor(mins/60)+'時間'+(mins%60?mins%60+'分':''):mins+'分'})の間でランダムに投稿`;}
function closeBulk(){BK=null;$('#bulkpanel').hidden=true;$('#bulkpanel').innerHTML='';}
function drawBulk(){
  const pn=$('#bulkpanel'),B=BK;if(!B)return;
  let body='';
  if(B.state==='form'){
    const ps=PROFILES||[],q=B.q.toLowerCase(),list=ps.filter(p=>!q||p.name.toLowerCase().includes(q)||p.group.includes(q));
    const groups=[...new Set(list.map(p=>p.group))];
    const n=B.sel.size,total=n*B.per;
    body=`<div class="field"><div class="row" style="justify-content:space-between;margin-bottom:6px"><div class="l" style="margin:0">アカウント(${n}件選択中)</div>
        <div class="row"><button class="btn" id="ball" style="padding:4px 10px">表示中を全選択</button><button class="btn" id="bcond" style="padding:4px 10px" title="imp 500以下 かつ 前回投稿から6時間以上経過(imp・前回投稿が分かるアカウントのみ)">500imp以下・6h経過を選択</button><button class="btn" id="bimp" style="padding:4px 10px"${B.impBusy?' disabled':''}>${B.impBusy?`imp取得中 ${B.impBusy.done}/${B.impBusy.total}…`:'📈 imp更新'}</button><button class="btn" id="bnone" style="padding:4px 10px">解除</button></div></div>
      <input id="bq" type="text" placeholder="名前・グループで絞り込み" value="${esc(B.q)}"></div>
      <div class="accs" style="max-height:260px;overflow:auto">${!PROFILES?'<div class="note">読み込み中…</div>':groups.map(g=>`<div class="grp">${esc(g)}</div>${list.filter(p=>p.group===g).map(p=>`<button class="acc" role="checkbox" aria-checked="${B.sel.has(p.id)}" data-b="${p.id}"><span class="mark"></span>${avt(p)}${esc(p.name)} ${sbBadge(p)}<span class="lastp" title="${p.imp&&p.imp.fetched_at?esc('imp取得 '+p.imp.fetched_at.slice(5,16).replace('T',' ')):''}">${esc(impTxt(p))} ／ ${esc(lastTxt(p))}</span></button>`).join('')}`).join('')}</div>
      <div class="note" style="margin-top:8px">⚫=未判定 🟢=問題なし 🟡=注意(理由を併記) 🔴=規制の疑い(判定は上部の「🔍 シャドウバン判定」から)</div>
      <div class="field" style="margin-top:14px"><div class="l">投稿する時間帯</div>
        <div class="row" style="margin-bottom:8px"><span class="note" style="margin:0">日付</span>${dsel('bsd',B.sd)}</div>
        <div class="row chipsrow" style="margin-bottom:8px"><span class="note" style="margin:0">よく使う時間帯</span>${BPRE.map(x=>`<button class="chip" data-pre="${x[0]}" aria-pressed="${B.preset===x[0]}">${x[0]} ${x[1]}〜${x[2]}</button>`).join('')}</div>
        <div class="row"><span class="note" style="margin:0">細かく指定</span>${tsel('bst',B.st)} 〜 ${dsel('bed',B.ed)}${tsel('bet',B.et)}</div>
        <div class="note" style="margin-top:6px">${esc(bSummary(B))}</div></div>
      <div class="field"><div class="l">1アカウントあたりの投稿数</div><input type="number" id="bper" min="1" max="20" value="${B.per}" style="width:90px"></div>
      <div class="note">作品はボードの中からランダムに選びます(同じアカウントで投稿・予約済みの動画は除外(同じ作品でも別の動画ならOK))。本文のリライトと動画加工も自動で行います。合計 <b>${total}</b> 件を、指定の時間帯の中でランダムな時刻に予約します。</div>
      <div style="margin-top:14px"><button class="btn go block" id="brun" ${n&&new Date(bEnd(B))>new Date(bStart(B))?'':'disabled'}>${total}件を一括予約する</button></div>`;
  }else if(B.state==='busy'){
    const st=B.st||{total:0,done:0};
    body=`<div class="result"><div class="spin" style="margin:12px auto"></div><h3>予約を作成中…</h3>
      <div class="note">${st.done} / ${st.total||'?'} 件(リライトと動画加工に時間がかかります。この画面を閉じても処理は続きます)</div></div>`;
  }else{
    const st=B.st;
    const okN=st.total-st.errors.length;
    body=`<div class="result"><div style="font-size:42px">${okN>0?'✅':'⚠️'}</div><h3>${okN>0?`${okN}件を予約しました`:'予約できませんでした'}</h3>
      ${[...st.notes,...st.errors].map(x=>`<div class="note" style="color:var(--warn)">${esc(x)}</div>`).join('')}
      <div class="row" style="justify-content:center;margin-top:16px"><button class="btn primary" id="bshow">予約一覧で確認・取り消し</button><button class="btn" id="bclose2">閉じる</button></div></div>`;
  }
  const oldAcc=pn.querySelector('.accs'),keepTop=oldAcc?oldAcc.scrollTop:0,oldContent=pn.querySelector('.content'),keepC=oldContent?oldContent.scrollTop:0;
  pn.innerHTML=`<div class="sheet"><header><h2>一括予約投稿</h2><button class="iconbtn" id="bclose" aria-label="閉じる">✕</button></header><div class="content">${body}</div></div>`;
  const na=pn.querySelector('.accs');if(na)na.scrollTop=keepTop;const nc=pn.querySelector('.content');if(nc)nc.scrollTop=keepC;
  $('#bclose').onclick=closeBulk;
  const c2=$('#bclose2');if(c2)c2.onclick=closeBulk;
  const sh=$('#bshow');if(sh)sh.onclick=()=>{closeBulk();openSched();};
  pn.querySelectorAll('[data-b]').forEach(b=>b.onclick=()=>{B.sel.has(b.dataset.b)?B.sel.delete(b.dataset.b):B.sel.add(b.dataset.b);drawBulk();});
  const bq=$('#bq');if(bq)bq.oninput=e=>{B.q=e.target.value;const pos=e.target.selectionStart;drawBulk();const n=$('#bq');n.focus();n.setSelectionRange(pos,pos);};
  const vis=()=>(PROFILES||[]).filter(p=>!B.q||p.name.toLowerCase().includes(B.q.toLowerCase())||p.group.includes(B.q)).map(p=>p.id);
  const ba=$('#ball');if(ba)ba.onclick=()=>{vis().forEach(i=>B.sel.add(i));drawBulk();};
  const bc=$('#bcond');if(bc)bc.onclick=()=>{
    const now=Date.now(),ok=p=>p.imp&&p.imp.views!=null&&p.imp.views<=500&&p.last&&now-new Date(p.last).getTime()>=6*3600*1000;
    const vs=new Set(vis()),hit=(PROFILES||[]).filter(p=>vs.has(p.id)&&ok(p)).map(p=>p.id);
    B.sel.clear();hit.forEach(i=>B.sel.add(i));drawBulk();
    toast(hit.length?`${hit.length}件を選択しました(imp 500以下・前回投稿から6時間以上)`:'条件に合うアカウントがありません',!hit.length);
  };
  const bn=$('#bnone');if(bn)bn.onclick=()=>{B.sel.clear();drawBulk();};
  const bsd=$('#bsd');if(bsd)bsd.onchange=e=>{const old=B.sd;B.sd=e.target.value;
    // 開始日を変えたら、終了日も同じ日数ぶんずらす(日をまたぐ設定を保つ)
    const diff=(new Date(B.ed)-new Date(old))/864e5;const d=new Date(B.sd);d.setDate(d.getDate()+diff);B.ed=ymd(d);drawBulk();};
  const bs=$('#bst');if(bs)bs.onchange=e=>{B.st=e.target.value;B.preset='';drawBulk();};
  const be=$('#bed');if(be)be.onchange=e=>{B.ed=e.target.value;B.preset='';drawBulk();};
  const bt=$('#bet');if(bt)bt.onchange=e=>{B.et=e.target.value;B.preset='';drawBulk();};
  pn.querySelectorAll('[data-pre]').forEach(b=>b.onclick=()=>{applyPre(B,BPRE.find(x=>x[0]===b.dataset.pre));drawBulk();});
  const bp=$('#bper');if(bp)bp.onchange=e=>{B.per=Math.min(20,Math.max(1,+e.target.value||1));drawBulk();};
  const bi=$('#bimp');if(bi)bi.onclick=async()=>{
    if(B.impBusy)return;
    try{
      const ids=(PROFILES||[]).filter(p=>p.has_post).map(p=>p.id);
      if(!ids.length){toast('投稿履歴のあるアカウントがありません',true);return;}
      const o=await api('/api/imps',{method:'POST',body:JSON.stringify({profile_ids:ids})});
      B.impBusy={done:0,total:ids.length};drawBulk();
      for(;;){
        await new Promise(r=>setTimeout(r,1500));
        const st=await api('/api/imps/'+o.job);
        B.impBusy={done:st.done,total:st.total};
        PROFILES=await api('/api/profiles');
        if(st.state!=='running')break;
        if(BK===B)drawBulk();
      }
      toast('imp を更新しました ✓');
    }catch(e){toast('imp数の取得に失敗: '+e.message,true);}
    B.impBusy=null;if(BK===B)drawBulk();
  };
  const br=$('#brun');if(br)br.onclick=runBulk;
}
/* ===== 最新投稿のimp ===== */
let IMP=null;
const fmtN=n=>n==null?'-':Number(n).toLocaleString();
async function openImp(){
  IMP={q:'',busy:null};
  $('#imppanel').hidden=false;drawImp();
  try{PROFILES=await api('/api/profiles');}catch(e){toast('アカウント一覧を取得できません: '+e.message,true);}
  if(IMP)drawImp();
}
function closeImp(){IMP=null;$('#imppanel').hidden=true;$('#imppanel').innerHTML='';}
function drawImp(){
  const pn=$('#imppanel'),B=IMP;if(!B)return;
  const ps=PROFILES||[],q=B.q.toLowerCase(),list=ps.filter(p=>!q||p.name.toLowerCase().includes(q)||p.group.includes(q));
  const groups=[...new Set(list.map(p=>p.group))],n=ps.filter(p=>p.has_post).length;
  const keepEl=pn.querySelector('.accs'),keep=keepEl?keepEl.scrollTop:0;
  const row=p=>{const i=p.imp;
    const val=!p.has_post?'<span class="lastp">投稿なし</span>':!i?'<span class="lastp">未取得</span>':i.views==null?`<span class="lastp">取得失敗</span>`
      :`<span class="lastp"><b>${fmtN(i.views)}</b> imp ・♥${fmtN(i.likes)} ・🔁${fmtN(i.retweets)} ・🔖${fmtN(i.bookmarks)}</span>`;
    const link=i&&i.screen_name?` <a href="https://x.com/${esc(i.screen_name)}/status/${esc(i.tweet_id)}" target="_blank" rel="noopener">開く</a>`:'';
    return `<div class="acc" style="cursor:default"><span class="mark" style="visibility:hidden"></span>${avt(p)}${esc(p.name)}${link} ${val}${i&&i.fetched_at?`<span class="lastp" style="margin-left:6px">${esc(fmtAt(i.posted_at).slice(5))}投稿 / ${esc(i.fetched_at.slice(5,16).replace('T',' '))}取得</span>`:''}</div>`;};
  pn.innerHTML=`<div class="sheet"><header><h2>直前投稿のimp数取得</h2><button class="iconbtn" id="impclose" aria-label="閉じる">✕</button></header><div class="content">
    <div class="note" style="margin-top:0">各アカウントの「このボードから投稿した最新の1件」の表示回数などを取得します(投稿履歴のあるアカウント: ${n}件)。</div>
    <div class="field"><input id="impq" type="text" placeholder="名前・グループで絞り込み" value="${esc(B.q)}"></div>
    <div class="accs" style="max-height:380px;overflow:auto">${!PROFILES?'<div class="note">読み込み中…</div>':groups.map(g=>`<div class="grp">${esc(g)}</div>${list.filter(p=>p.group===g).map(row).join('')}`).join('')}</div>
    <div style="margin-top:14px"><button class="btn go block" id="imprun" ${n&&!B.busy?'':'disabled'}>${B.busy?`取得中 ${B.busy.done}/${B.busy.total}…`:`全アカウントのimpを取得する(${n}件)`}</button></div></div></div>`;
  const na=pn.querySelector('.accs');if(na)na.scrollTop=keep;
  $('#impclose').onclick=closeImp;
  $('#impq').oninput=e=>{B.q=e.target.value;const pos=e.target.selectionStart;drawImp();const t=$('#impq');t.focus();t.setSelectionRange(pos,pos);};
  $('#imprun').onclick=runImp;
}
async function runImp(){
  const B=IMP;if(!B||B.busy)return;
  try{
    const ids=(PROFILES||[]).filter(p=>p.has_post).map(p=>p.id);
    const o=await api('/api/imps',{method:'POST',body:JSON.stringify({profile_ids:ids})});
    B.busy={done:0,total:ids.length};drawImp();
    for(;;){
      await new Promise(r=>setTimeout(r,1500));
      const st=await api('/api/imps/'+o.job);
      B.busy={done:st.done,total:st.total};
      PROFILES=await api('/api/profiles');
      if(st.state!=='running')break;
      if(IMP===B)drawImp();
    }
    toast('imp を取得しました ✓');
    if(IMP===B){B.busy=null;drawImp();}
  }catch(e){if(IMP===B){B.busy=null;drawImp();}toast('取得に失敗: '+e.message,true);}
}
$('#impbtn').onclick=openImp;
$('#imppanel').addEventListener('click',e=>{if(e.target.id==='imppanel')closeImp();});
/* ===== シャドウバン判定 ===== */
let SB=null;
async function openSb(){
  SB={sel:new Set(),q:'',busy:null};
  $('#sbpanel').hidden=false;drawSb();
  try{PROFILES=await api('/api/profiles');}catch(e){toast('アカウント一覧を取得できません: '+e.message,true);}
  if(SB)drawSb();
}
function closeSb(){SB=null;$('#sbpanel').hidden=true;$('#sbpanel').innerHTML='';}
function drawSb(){
  const pn=$('#sbpanel'),B=SB;if(!B)return;
  const ps=PROFILES||[],q=B.q.toLowerCase(),list=ps.filter(p=>!q||p.name.toLowerCase().includes(q)||p.group.includes(q));
  const groups=[...new Set(list.map(p=>p.group))],n=B.sel.size;
  const cnt=l=>ps.filter(p=>p.sb&&p.sb.level===l).length;
  const oldAcc=pn.querySelector('.accs'),keep=oldAcc?oldAcc.scrollTop:0;
  pn.innerHTML=`<div class="sheet"><header><h2>シャドウバン判定</h2><button class="iconbtn" id="sbclose" aria-label="閉じる">✕</button></header><div class="content">
    <div class="note" style="margin-top:0">🟢 ${cnt('ok')} / 🟡 ${cnt('warn')} / 🔴 ${cnt('bad')} / ⚪ ${cnt('unknown')} / ⚫ 未判定 ${ps.filter(p=>!p.sb).length}</div>
    <div class="field"><div class="row" style="justify-content:space-between;margin-bottom:6px"><div class="l" style="margin:0">アカウント(${n}件選択中)</div>
      <div class="row"><button class="btn" id="sball" style="padding:4px 10px">表示中を全選択</button><button class="btn" id="sbunj" style="padding:4px 10px">未判定だけ選択</button><button class="btn" id="sbnone" style="padding:4px 10px">解除</button></div></div>
      <input id="sbq" type="text" placeholder="名前・グループで絞り込み" value="${esc(B.q)}"></div>
    <div class="accs" style="max-height:340px;overflow:auto">${!PROFILES?'<div class="note">読み込み中…</div>':groups.map(g=>`<div class="grp">${esc(g)}</div>${list.filter(p=>p.group===g).map(p=>`<button class="acc" role="checkbox" aria-checked="${B.sel.has(p.id)}" data-sb="${p.id}"><span class="mark"></span>${avt(p)}${esc(p.name)} ${sbBadge(p)}<span class="lastp">${p.sb?esc('判定 '+p.sb.checked_at.slice(5,16).replace('T',' ')):''}</span></button>`).join('')}`).join('')}</div>
    <div style="margin-top:14px"><button class="btn go block" id="sbrun" ${n&&!B.busy?'':'disabled'}>${B.busy?`判定中 ${B.busy.done}/${B.busy.total}…`:`${n}件をシャドウバン判定する`}</button>
    <div class="note" style="text-align:center">1件あたり約20秒かかります。判定は Xdeck が、対象とは別のアカウントの通信で行います。この画面を閉じても処理は続きます。</div></div></div></div>`;
  const na=pn.querySelector('.accs');if(na)na.scrollTop=keep;
  $('#sbclose').onclick=closeSb;
  pn.querySelectorAll('[data-sb]').forEach(b=>b.onclick=()=>{B.sel.has(b.dataset.sb)?B.sel.delete(b.dataset.sb):B.sel.add(b.dataset.sb);drawSb();});
  const vis=()=>list.map(p=>p.id);
  $('#sball').onclick=()=>{vis().forEach(i=>B.sel.add(i));drawSb();};
  $('#sbunj').onclick=()=>{B.sel.clear();list.filter(p=>!p.sb).forEach(p=>B.sel.add(p.id));drawSb();};
  $('#sbnone').onclick=()=>{B.sel.clear();drawSb();};
  $('#sbq').oninput=e=>{B.q=e.target.value;const pos=e.target.selectionStart;drawSb();const t=$('#sbq');t.focus();t.setSelectionRange(pos,pos);};
  $('#sbrun').onclick=runSb;
}
async function runSb(){
  const B=SB;if(!B||!B.sel.size||B.busy)return;
  try{
    const o=await api('/api/shadowban',{method:'POST',body:JSON.stringify({profile_ids:[...B.sel]})});
    B.busy={done:0,total:B.sel.size};drawSb();
    for(;;){
      await new Promise(r=>setTimeout(r,3000));
      const st=await api('/api/shadowban/'+o.job);
      B.busy={done:st.done,total:st.total};
      PROFILES=await api('/api/profiles');
      if(st.state!=='running')break;
      if(SB===B)drawSb();
    }
    toast('シャドウバン判定が完了しました ✓');
    if(SB===B){B.busy=null;B.sel.clear();drawSb();}
  }catch(e){if(SB===B){B.busy=null;drawSb();}toast('判定に失敗: '+e.message,true);}
}
$('#sbbtn').onclick=openSb;
$('#sbpanel').addEventListener('click',e=>{if(e.target.id==='sbpanel')closeSb();});
async function runBulk(){
  const B=BK;if(!B||B.sel.size===0)return;
  try{
    const o=await api('/api/bulk',{method:'POST',body:JSON.stringify({profile_ids:[...B.sel],start:bStart(B),end:bEnd(B),per:B.per})});
    B.state='busy';B.st={total:0,done:0};drawBulk();
    for(;;){
      await new Promise(r=>setTimeout(r,2000));
      if(BK!==B){refreshSchedCount();return;}
      const st=await api('/api/bulk/'+o.job);B.st=st;
      if(st.state!=='running'){B.state='done';break;}
      drawBulk();
    }
    refreshSchedCount();drawBulk();
  }catch(e){if(BK===B){B.state='form';drawBulk();}toast('失敗: '+e.message,true);}
}

/* ===== 定常予約(毎日決まった時間帯の自動予約) ===== */
let ROUT=null;
const RT_STATE={plan:['wait','予定'],running:['busy','作成中'],done:['ok','予約済み'],error:['err','失敗'],skip:['','この日は休み'],off:['','OFF'],late:['','時間切れ(未実行)']};
const RT_LABEL={am:'朝',pm:'午後',night:'夜'};
const rtEnd=[...TIMES.slice(1),'24:00'];
function rsel(id,val,end){const ts=(end?rtEnd:TIMES).includes(val)?(end?rtEnd:TIMES):[...(end?rtEnd:TIMES),val].sort();return `<select id="${id}" class="tsel">${ts.map(t=>`<option ${t===val?'selected':''}>${t}</option>`).join('')}</select>`;}
async function openRout(){ROUT={data:null,edit:null,busy:false};$('#routpanel').hidden=false;drawRout();await loadRout();}
function closeRout(){ROUT=null;$('#routpanel').hidden=true;$('#routpanel').innerHTML='';}
async function loadRout(){const R=ROUT;try{const d=await api('/api/routine');if(ROUT===R){R.data=d;drawRout();}}catch(e){toast('定常予約の取得に失敗: '+e.message,true);}}
async function routCall(method,path,body,msg){
  const R=ROUT;if(!R||R.busy)return;R.busy=true;
  try{const r=await api(path,{method,body:JSON.stringify(body)});if(msg)toast(msg(r));refreshSchedCount();}
  catch(e){toast('失敗: '+e.message,true);}
  R.busy=false;R.edit=null;if(ROUT===R)await loadRout();
}
function drawRout(){
  const pn=$('#routpanel'),R=ROUT;if(!R)return;const D=R.data;
  let body='<div class="note">読み込み中…</div>';
  if(D){
    const lbl=s=>s.label||RT_LABEL[s.id]||s.id;
    const sl=Object.fromEntries(D.slots.map(s=>[s.id,s]));
    const base=D.slots.map(s=>`<div class="row" style="margin-bottom:8px;gap:8px;flex-wrap:wrap"><label class="row" style="gap:6px;min-width:84px"><input type="checkbox" data-en="${s.id}" ${s.enabled?'checked':''}><b>${esc(lbl(s))}</b></label>
      ${rsel('rs-'+s.id,s.start)} 〜 ${rsel('re-'+s.id,s.end,true)}
      <span class="note" style="margin:0">${s.mode==='imp_below'?`この日の前の投稿が <input type="number" min="0" id="ri-${s.id}" value="${s.imp_max??1000}" style="width:80px"> imp以下のアカウントだけ(開始時刻にimpを取得)`:'全アカウント'}</span></div>`).join('');
    const days=D.days.map((d,i)=>`<div class="field" style="margin-bottom:10px"><div class="l">${d.date.slice(5).replace('-','/')}(${d.wd})${i===0?' 今日':i===1?' 明日':''}</div>${d.slots.map(x=>{
      const key=d.date+':'+x.id,st=RT_STATE[x.state]||['',x.state],run=x.run||{},ed=R.edit===key;
      const detail=x.state==='done'||x.state==='error'?`<div class="note" style="margin:2px 0 0">${run.reserved??0}件を予約${run.candidates!=null?`(対象${run.candidates}アカウント)`:''}${(run.errors||[]).length?` / エラー${run.errors.length}件`:''}</div>${[...(run.notes||[]),...(run.errors||[]).slice(0,5)].map(n=>`<div class="note" style="margin:2px 0 0;color:var(--warn)">${esc(n)}</div>`).join('')}`:'';
      return `<div class="srow" style="align-items:flex-start"><div class="when" style="min-width:150px"><b>${esc(lbl(sl[x.id]))}</b> ${x.start}〜${x.end}${x.changed&&!x.skip?' <span class="note" style="margin:0">(この日だけ変更)</span>':''}</div>
        <div class="main">${badge(st[0],esc(st[1]))}${detail}
        ${ed?`<div class="row" style="margin-top:8px;gap:6px">${rsel('ds',x.start)} 〜 ${rsel('de',x.end,true)}<button class="btn primary sm" data-dsave="${key}">この日だけ変更</button><button class="btn sm" data-dcancel>やめる</button></div>`:''}</div>
        <div class="row" style="flex-direction:column;gap:6px">${!ed&&x.state!=='running'&&x.state!=='off'?`<button class="btn sm" data-dedit="${key}">時間を変える</button>`:''}${!ed&&x.state==='skip'?`<button class="btn sm" data-dclear="${key}">休みをやめる</button>`:''}${!ed&&['plan','done','error'].includes(x.state)?`<button class="btn sm" data-dskip="${key}">この日は休む</button>`:''}${!ed&&x.changed&&!x.skip?`<button class="btn sm" data-dclear="${key}">基本に戻す</button>`:''}${['done','error'].includes(x.state)?`<button class="btn sm danger" data-drebuild="${key}">作り直す</button>`:''}</div></div>`;}).join('')}</div>`).join('');
    body=`<div class="row" style="justify-content:space-between;margin-bottom:12px"><label class="row" style="gap:8px;font-size:15px"><input type="checkbox" id="rtmaster" ${D.enabled?'checked':''}><b>定常予約を有効にする</b></label>
        <span class="note" style="margin:0">${D.enabled?'ON: 各時間帯の'+D.lead_min+'分前に自動で予約を作ります':'OFF: 何も自動予約しません'}</span></div>
      <div class="field"><div class="l">基本の時間帯(毎日)</div>${base}
        <button class="btn primary" id="rtsave">基本の時間帯を保存</button>
        <div class="note">各アカウント1日1回、時間帯の中のランダムな時刻に予約します(作品選び・リライト・動画加工は一括予約と同じ)。${IS_ENT?'':'午後は、開始時刻にその日の朝の投稿のimpを取得して、しきい値以下のアカウントだけ予約します(その日まだ投稿していないアカウントは対象)。'}保存すると、まだ予約を作っていない日に反映されます。</div></div>
      <div class="field"><div class="l">今後7日間(日ごとの変更)</div>${days}
        <div class="note">予約済みの時間帯を変更・休みにすると、待機中の予約を取り消して作り直します(投稿済みのものは残ります)。個別の取り消しは「予約履歴」から。</div></div>`;
  }
  const keep=pn.querySelector('.content'),top=keep?keep.scrollTop:0;
  pn.innerHTML=`<div class="sheet"><header><h2>定常予約</h2><button class="iconbtn" id="rtclose" aria-label="閉じる">✕</button></header><div class="content">${body}</div></div>`;
  const nc=pn.querySelector('.content');if(nc)nc.scrollTop=top;
  $('#rtclose').onclick=closeRout;if(!D)return;
  $('#rtmaster').onchange=e=>routCall('PUT','/api/routine/config',{enabled:e.target.checked},()=>e.target.checked?'定常予約をONにしました':'定常予約をOFFにしました');
  $('#rtsave').onclick=()=>routCall('PUT','/api/routine/config',{slots:D.slots.map(s=>({id:s.id,start:$('#rs-'+s.id).value,end:$('#re-'+s.id).value,enabled:pn.querySelector(`[data-en="${s.id}"]`).checked,...(s.mode==='imp_below'?{imp_max:+$('#ri-'+s.id).value}:{})}))},()=>'保存しました ✓');
  const split=k=>({date:k.slice(0,10),slot:k.slice(11)});
  pn.querySelectorAll('[data-dedit]').forEach(b=>b.onclick=()=>{R.edit=b.dataset.dedit;drawRout();});
  pn.querySelectorAll('[data-dcancel]').forEach(b=>b.onclick=()=>{R.edit=null;drawRout();});
  pn.querySelectorAll('[data-dsave]').forEach(b=>b.onclick=()=>routCall('PUT','/api/routine/day',{...split(b.dataset.dsave),start:$('#ds').value,end:$('#de').value},r=>r.cancelled?`変更しました(待機中の${r.cancelled}件を取り消して作り直します)`:'この日だけ変更しました ✓'));
  pn.querySelectorAll('[data-dskip]').forEach(b=>b.onclick=()=>{if(!confirm('この日のこの時間帯は休みにします。予約済みの待機中の予約は取り消されます。よろしいですか?'))return;
    routCall('PUT','/api/routine/day',{...split(b.dataset.dskip),skip:true},r=>r.cancelled?`休みにしました(${r.cancelled}件を取り消し)`:'この日は休みにしました ✓');});
  pn.querySelectorAll('[data-dclear]').forEach(b=>b.onclick=()=>routCall('PUT','/api/routine/day',{...split(b.dataset.dclear),clear:true},r=>r.cancelled?`基本に戻しました(待機中の${r.cancelled}件を取り消して作り直します)`:'基本の時間帯に戻しました ✓'));
  pn.querySelectorAll('[data-drebuild]').forEach(b=>b.onclick=()=>{if(!confirm('待機中の予約を取り消して、もう一度作り直します。よろしいですか?'))return;
    routCall('POST','/api/routine/rebuild',split(b.dataset.drebuild),r=>`${r.cancelled}件を取り消しました。まもなく作り直します`);});
}
$('#routbtn').onclick=openRout;
$('#routpanel').addEventListener('click',e=>{if(e.target.id==='routpanel')closeRout();});
setInterval(()=>{if(ROUT&&!ROUT.edit&&!ROUT.busy&&!$('#routpanel').hidden)loadRout();},20000);
$('#bulkbtn').onclick=openBulk;
$('#bulkpanel').addEventListener('click',e=>{if(e.target.id==='bulkpanel')closeBulk();});
function myfansPost(w){for(const u of w.urls||[]){const m=/^https:\/\/myfans\.jp\/posts\/([0-9a-f-]{36})/i.exec(u.url);if(m)return `https://myfans.jp/posts/${m[1]}`;}return '';}
let SCHED=[];
const SLBL={pending:['wait','🕒 待機中(時刻になると投稿)'],running:['busy','投稿中'],done:['ok','投稿済み'],failed:['err','失敗'],missed:['err','見送り(時刻に停止中)']};
async function refreshSchedCount(){
  try{SCHED=await api('/api/schedule');}catch(e){return;}
  const n=SCHED.filter(x=>x.status==='pending'||x.status==='running').length;
  {const bd=$('#schedbtn .badge');bd.textContent=n;bd.hidden=!n;}
  if(!$('#schedpanel').hidden)drawSched();
}
function remain(at){const m=Math.round((new Date(at)-Date.now())/6e4);
  if(m<=0)return 'まもなく';if(m<60)return `あと${m}分`;const h=Math.floor(m/60);return h<24?`あと${h}時間${m%60}分`:`あと${Math.floor(h/24)}日${h%24}時間`;}
function openSched(){$('#schedpanel').hidden=false;drawSched();refreshSchedCount();}
function closeSched(){$('#schedpanel').hidden=true;}
function drawSched(){
  const pn=$('#schedpanel');
  const rows=[...SCHED].sort((a,b)=>a.at<b.at?1:a.at>b.at?-1:0).map(x=>{const st=SLBL[x.status]||['',x.status];
    return `<div class="srow"><div class="when">${esc(fmtAt(x.at))}${x.status==='pending'?`<div class="note" style="margin:2px 0 0">${esc(remain(x.at))}</div>`:''}</div><div class="main"><b>${esc(x.profile_name)}</b> ${badge(st[0],esc(st[1]))}
      <div class="stx">${esc(x.text)}</div>${x.error?`<div class="note" style="color:var(--err)">${esc(x.error)}</div>`:''}
      ${x.status==='pending'&&x.auto_retries?`<div class="note" style="color:var(--warn)">自動再実行 ${x.auto_retries}回目の待機中(前回の失敗: ${esc(x.last_error||'')})</div>`:''}${(x.retry_log||[]).map(l=>`<div class="note" style="margin:2px 0 0">${esc(l)}</div>`).join('')}
      ${x.link?`<a href="${esc(x.link)}" target="_blank" rel="noopener">X で開く</a>`:''}</div>
      <div class="row" style="flex-direction:column;gap:6px">${x.status==='failed'||x.status==='missed'?`<button class="btn primary" data-retry="${esc(x.id)}">再試行</button>`:''}<button class="btn sdel" data-s="${esc(x.id)}" ${x.status==='running'?'disabled':''}>${x.status==='pending'?'取り消す':'削除'}</button></div></div>`;}).join('');
  const nfail=SCHED.filter(x=>x.status==='failed'||x.status==='missed').length;
  pn.innerHTML=`<div class="sheet"><header><h2>予約履歴</h2><button class="iconbtn" id="sclose" aria-label="閉じる">✕</button></header>
    <div class="content">${nfail?`<div style="margin-bottom:10px"><button class="btn primary" id="retryall">失敗・見送り ${nfail}件をすべて再試行</button></div>`:''}${rows||'<div class="note">予約はありません。投稿画面の最後のステップで「日時を指定して予約」を選ぶと追加できます。</div>'}
    <div class="note">予約時刻にこのMacで Bot が起動している必要があります。時刻を${30}分以上過ぎて起動した場合は、投稿せず「見送り」になります。</div></div></div>`;
  $('#sclose').onclick=closeSched;
  const retry=async(id,btn)=>{
    if(btn)btn.disabled=true;
    try{const r=await api('/api/schedule/'+id+'/retry',{method:'POST'});toast(r.retried?`${r.retried}件を再試行します(数十秒以内に投稿)`:'再試行できる予約がありません',!r.retried);}
    catch(e){toast('再試行に失敗: '+e.message,true);}
    refreshSchedCount();};
  const ra=$('#retryall');if(ra)ra.onclick=()=>retry('all',ra);
  pn.querySelectorAll('[data-retry]').forEach(b=>b.onclick=()=>retry(b.dataset.retry,b));
  pn.querySelectorAll('.sdel').forEach(b=>b.onclick=async()=>{
    try{await api('/api/schedule/'+b.dataset.s,{method:'DELETE'});}catch(e){toast('失敗: '+e.message,true);}refreshSchedCount();});
}
$('#schedbtn').onclick=openSched;
$('#schedpanel').addEventListener('click',e=>{if(e.target.id==='schedpanel')closeSched();});
setInterval(refreshSchedCount,30000);refreshSchedCount();
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;if(!$('#imppanel').hidden)closeImp();else if(!$('#sbpanel').hidden)closeSb();else if(!$('#routpanel').hidden)closeRout();else if(!$('#bulkpanel').hidden)closeBulk();else if(!$('#schedpanel').hidden)closeSched();else if(!$('#modal').hidden)closePost();else if(openId)closeDrawer();});
// URL から直接開ける: #w=作品ID / #post=作品ID&step=2
load().then(()=>{
  const h=new URLSearchParams(location.hash.slice(1));
  if(h.get('w'))openDrawer(h.get('w'));
  if(h.get('post')){const w=works.find(x=>x.work_id===h.get('post'));if(w){openDrawer(w.work_id);openPost(w);if(h.get('step'))P.step=+h.get('step'),renderPost();}}
});

/* ===== 接続状態(右上の緑/赤の点) ===== */
(function(){
  const el=$('#conn');let fails=0;
  const chip=(name,st)=>{const cls=st?(st.ok?'':' bad'):' unk',mark=st&&!st.ok?'! ':'';
    return `<span class="c${cls}" title="${esc(name+': '+(st?st.msg:'確認できません(ボードに接続できません)'))}"><span class="d"></span><span class="t">${mark}${name}</span></span>`;};
  async function tick(){
    let d=null;
    try{d=await api('/api/status');fails=0;}catch{fails++;}
    // ボード自体に届かないときは、どちらも不明(灰色)ではなく赤で知らせる
    if(!d&&fails>=2)d={discord:{ok:false,msg:'ボードに接続できません(アプリが止まっている可能性)'},xdeck:{ok:false,msg:'ボードに接続できません'}};
    if(d)el.innerHTML=chip('Discord',d.discord)+chip('Xdeck',d.xdeck);
  }
  tick();setInterval(tick,10000);
})();
