/* Pekerjaan cetak dipisahkan dari tampilan. Tidak masuk antrean luring timbang. */
(function(){
'use strict';
var root=document.querySelector('[data-cetak-halaman]');if(!root||root.dataset.aktif)return;root.dataset.aktif='1';
var $=function(s){return root.querySelector(s);};
var job=JSON.parse($('[data-cp-job]').textContent),busy=false;
var storage='tf-cetak:'+root.dataset.identitas,key='';
try{key=sessionStorage.getItem(storage+':kunci')||'';$('[name=alasan]').value=sessionStorage.getItem(storage+':alasan')||'';}catch(e){}
function simpan(k,v){try{sessionStorage.setItem(storage+':'+k,v);}catch(e){}}
$('[name=alasan]').addEventListener('input',function(){simpan('alasan',this.value);});
function format(){return $('[name=cp-format]:checked').value;}
function keluaran(){return format()==='NCR'?'pdf':$('[name=cp-keluaran]:checked').value;}
function pesan(t){$('[data-cp-status]').hidden=!t;$('[data-cp-status]').textContent=t;}
function pilihan(){
 var f=format(),pdf=keluaran()==='pdf';
 root.querySelectorAll('[data-paper]').forEach(function(x){x.hidden=x.dataset.paper!==f;});
 $('[data-keluaran]').hidden=f==='NCR';$('[data-ncr-note]').hidden=f!=='NCR';$('[data-printer-info]').hidden=pdf;
 $('[data-cp-jalankan]').textContent=pdf?'Siapkan PDF':'Cetak langsung';
 $('[data-cp-keterangan]').textContent=pdf?'PDF siap belum berarti kertas sudah tercetak. Catat hanya setelah hasil fisik diperiksa.':'Cetak fisik dicatat setelah jawaban printer berhasil atau dikonfirmasi petugas.';
 var p=window.TeraFlowPrinter;$('[data-alamat-printer]').textContent=(p&&p.alamat())||'Belum disetel di perangkat ini';
 $('[data-cp-label]').textContent=(f==='NCR'?'Setengah NCR · 215 × 165 mm':'Struk 80 mm')+' · pratinjau revisi tiket saat halaman dibuka';
}
root.querySelectorAll('[name=cp-format],[name=cp-keluaran]').forEach(function(x){x.addEventListener('change',pilihan);});
function kunci(){root.querySelectorAll('[name=cp-format],[name=cp-keluaran],[name=alasan]').forEach(function(e){e.disabled=busy||!!job;});$('[data-cp-jalankan]').disabled=busy||!!(job&&job.status!=='siap');$('[data-cp-ya]').disabled=busy;$('[data-cp-tidak]').disabled=busy;}
function tampilJob(){
 $('[data-cp-pending]').hidden=!job;
 if(job){
  $('[name=cp-format][value="'+job.format+'"]').checked=true;
  $('[name=cp-keluaran][value="'+job.keluaran+'"]').checked=true;
  $('[name=alasan]').value=job.alasan;
  $('[data-pending-judul]').textContent=job.status==='pdf_siap'?'PDF siap · konfirmasi hasil fisik':job.status==='siap'?'Pekerjaan belum dikirim':'Hasil cetak perlu dipastikan';
  $('[data-pending-teks]').textContent=job.nama+' · '+job.format+' · revisi '+job.revisi+'. Periksa pekerjaan ini sebelum membuat cetakan lain.';
  $('[data-cp-ya]').hidden=job.status==='siap';
  if(job.status==='pdf_siap'){
   $('[data-cp-pdf]').href=root.dataset.tujuan+'/'+encodeURIComponent(job.kunci)+'/berkas';$('[data-cp-pdf]').hidden=false;
  }
 }
 pilihan();kunci();
}
async function minta(url,data){
 var ctrl=new AbortController(),timer=setTimeout(function(){ctrl.abort();},30000),r;
 try{r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{}),signal:ctrl.signal});}
 finally{clearTimeout(timer);}
 if(r.redirected)throw new Error('Sesi berubah. Masuk kembali dengan akun pencetak semula; isian tetap tersedia.');
 if(!r.ok){var d=await r.json().catch(function(){return {};});var err=new Error(d.error||'Server belum mengonfirmasi pekerjaan cetak.');err.status=r.status;throw err;}
 return r;
}
function segar(){simpan('kunci','');key='';location.reload();}
async function hasil(h){
 if(!job||busy)return;busy=true;kunci();
 try{
  var r=await minta(root.dataset.tujuan+'/'+job.kunci+'/hasil',{hasil:h}),j=await r.json();
  if(j.status==='berhasil'){simpan('alasan','');pesan('Cetak fisik tercatat.');segar();return;}
  job=null;simpan('kunci','');key='';$('[data-cp-pdf]').hidden=true;pesan('Belum ada cetak sukses yang ditambahkan. Tinjau pratinjau sebelum membuat perintah baru.');$('[data-cp-segar]').hidden=false;
 }catch(e){pesan(e.message+' Periksa status pekerjaan ini sebelum mencoba lagi.');}
 finally{busy=false;tampilJob();}
}
$('[data-cp-ya]').addEventListener('click',function(){hasil('dikonfirmasi');});
$('[data-cp-tidak]').addEventListener('click',function(){hasil('belum_tercetak');});
$('[data-cp-segar]').addEventListener('click',segar);
$('[data-cp-jalankan]').addEventListener('click',async function(){
 if(busy||(job&&job.status!=='siap'))return;
 var alasan=$('[name=alasan]');if(!job&&alasan.required&&!alasan.value.trim()){pesan('Isi alasan cetak ulang sebelum menyiapkan dokumen.');alasan.focus();alasan.reportValidity();return;}
 if(keluaran()==='printer'&&(!window.TeraFlowPrinter||!window.TeraFlowPrinter.alamat())){pesan('Printer belum disetel. Buka Siapkan printer, atau gunakan PDF.');return;}
 busy=true;kunci();pesan('Menyiapkan pekerjaan…');
 var sudahKirim=false;
 try{
  if(!job){
   if(!key){key=crypto.randomUUID?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(24)),function(x){return x.toString(16).padStart(2,'0');}).join('');simpan('kunci',key);}
   var r=await minta(root.dataset.tujuan,{kunci:key,format:format(),keluaran:keluaran(),alasan:alasan.value,sidik:root.dataset.sidik});job=await r.json();
  }
  if(job.status!=='siap'){pesan('Pekerjaan sudah diproses. Periksa hasilnya; perintah tidak dikirim ulang.');return;}
  var frozen=job;
  sudahKirim=true;
  // Status lokal juga dianggap belum pasti ketika jawaban pengiriman hilang.
  job.status=job.keluaran==='printer'?'dikirim':'pdf_siap';
  var data;
  try{data=await minta(root.dataset.tujuan+'/'+job.kunci+'/kirim');}
  catch(e){
   // Penolakan versi adalah jawaban pasti: belum ada XML dikirim ke alat.
   // Konflik perintah yang telah diproses tetap memerlukan pemeriksaan fisik.
   if(e.status===409&&e.message.includes('Data berubah')){job=null;key='';simpan('kunci','');sudahKirim=false;}
   throw e;
  }
  if(frozen.keluaran==='pdf'){
   if(!/application\/pdf/i.test(data.headers.get('Content-Type')||''))throw new Error('PDF belum terkonfirmasi.');
   pesan('PDF siap. Buka / unduh dokumen; belum ada cetak fisik yang dicatat.');
  }else{
   if(!/text\/xml/i.test(data.headers.get('Content-Type')||''))throw new Error('Perintah printer belum terkonfirmasi.');
   var xml=await data.text();pesan('Mengirim perintah ke printer…');
   try{await window.TeraFlowPrinter.kirim(null,xml);}
   catch(e){
    if(e.belumPasti){pesan(e.message+' Jangan kirim ulang otomatis; periksa kertas di printer.');return;}
    var gagal=await minta(root.dataset.tujuan+'/'+frozen.kunci+'/hasil',{hasil:'gagal'});await gagal.json();job=null;key='';simpan('kunci','');pesan(e.message+' Tidak dicatat sebagai cetak berhasil.');return;
   }
   pesan('Printer mengonfirmasi berhasil. Menyimpan riwayat…');
   var ack=await minta(root.dataset.tujuan+'/'+frozen.kunci+'/hasil',{hasil:'printer_berhasil'});var j=await ack.json();
   if(j.status!=='berhasil')throw new Error('Riwayat cetak belum terkonfirmasi.');
   simpan('alasan','');segar();
  }
 }catch(e){
  pesan(e.message+(sudahKirim?' Periksa hasil fisik; jangan mengirim ulang.':' Isian tetap tersedia.'));
  $('[data-cp-segar]').hidden=false;
 }finally{busy=false;tampilJob();}
});
tampilJob();
})();
