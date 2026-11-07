/* Pekerjaan cetak dipisahkan dari tampilan. Tidak masuk antrean luring timbang. */
(function(){
'use strict';
function pasang(root,opsi){
if(!root||root.dataset.aktif)return;root.dataset.aktif='1';opsi=opsi||{};
var $=function(s){return root.querySelector(s);};
function rangkap(){return job&&job.rangkap||2;}
var job=JSON.parse($('[data-cp-job]').textContent),busy=false;
// Alasan pengawasan terpisah dari alasan cetak milik pencetak semula.
var resolusi=document.createElement('label');resolusi.className='grup';
resolusi.textContent='Alasan penyelesaian oleh Admin';resolusi.hidden=true;
var alasanResolusi=document.createElement('textarea');alasanResolusi.name='alasan_penyelesaian';alasanResolusi.maxLength=2000;alasanResolusi.className='fld';
resolusi.append(alasanResolusi);$('[data-cp-pending]').insertBefore(resolusi,$('[data-cp-ya]'));

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
 $('[data-cp-jalankan]').textContent=pdf?'Siapkan cetak melalui PDF':'Cetak langsung · '+rangkap()+' rangkap';
 $('[data-cp-keterangan]').textContent=pdf?'Untuk mencetak ke kertas melalui PDF. Jika hanya membuka, mengunduh, atau berbagi, gunakan area Dokumen PDF di atas.':rangkap()+' rangkap dikirim dalam satu pekerjaan. Periksa seluruh lembar sebelum mengonfirmasi hasil fisik.';
 var p=window.TeraFlowPrinter;$('[data-alamat-printer]').textContent=(p&&p.alamat())||'Belum disetel di perangkat ini';
 $('[data-cp-label]').textContent=(f==='NCR'?'Setengah NCR · 215 × 165 mm':'Struk 80 mm')+' · pratinjau revisi tiket saat halaman dibuka';
}
root.querySelectorAll('[name=cp-format],[name=cp-keluaran]').forEach(function(x){x.addEventListener('change',pilihan);});
function kunci(){root.dataset.sibuk=busy?'1':'0';root.querySelectorAll('[name=cp-format],[name=cp-keluaran],[name=alasan]').forEach(function(e){e.disabled=busy||!!job;});$('[data-cp-jalankan]').disabled=busy||!!(job&&(job.status!=='siap'||job.boleh_menuntaskan));alasanResolusi.disabled=busy;$('[data-cp-ya]').disabled=busy;$('[data-cp-tidak]').disabled=busy;}
function tampilJob(){
 $('[data-cp-pending]').hidden=!job;
 resolusi.hidden=!(job&&job.boleh_menuntaskan);
 if(job){
  $('[name=cp-format][value="'+job.format+'"]').checked=true;
  $('[name=cp-keluaran][value="'+job.keluaran+'"]').checked=true;
  $('[name=alasan]').value=job.alasan;
  $('[data-pending-judul]').textContent=job.status==='pdf_siap'?'Cetak melalui PDF · konfirmasi hasil fisik':job.status==='siap'?'Pekerjaan belum dikirim':'Hasil cetak perlu dipastikan';
  $('[data-pending-teks]').textContent=job.nama+' · '+job.format+' · revisi '+job.revisi+'. Periksa seluruh '+(job.rangkap||1)+' rangkap pekerjaan ini sebelum membuat cetakan lain.';
  $('[data-cp-ya]').hidden=job.status==='siap';
  if(job.boleh_menuntaskan)$('[data-pending-teks]').textContent+=' Pekerjaan milik '+job.nama+'. Pastikan perangkat pencetak semula sudah berhenti mengirim. Periksa seluruh hasil fisik dan isi alasan sebelum menuntaskannya. Perintah tidak dikirim ulang.';
  $('[data-cp-tidak]').textContent=job.status==='siap'?'Batalkan pekerjaan yang belum dikirim':'Belum tercetak';
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
function segar(berhasil){simpan('kunci','');key='';if(opsi.segar){opsi.segar(berhasil===true);return;}location.reload();}
async function hasil(h){
 if(!job||busy)return;
 if(job.boleh_menuntaskan&&!alasanResolusi.value.trim()){pesan('Isi alasan penyelesaian setelah memeriksa hasil cetak petugas semula.');alasanResolusi.focus();return;}
 busy=true;kunci();
 try{
  var r=await minta(root.dataset.tujuan+'/'+job.kunci+'/hasil',{hasil:h,alasan_penyelesaian:alasanResolusi.value}),j=await r.json();
  if(j.status==='berhasil'){simpan('alasan','');pesan('Cetak fisik tercatat.');segar(true);return;}
  job=null;simpan('kunci','');key='';$('[data-cp-pdf]').hidden=true;pesan('Belum ada cetak sukses yang ditambahkan. Tinjau pratinjau sebelum membuat perintah baru.');$('[data-cp-segar]').hidden=false;
 }catch(e){pesan(e.message+' Periksa status pekerjaan ini sebelum mencoba lagi.');}
 finally{busy=false;tampilJob();}
}
$('[data-cp-ya]').addEventListener('click',function(){hasil('dikonfirmasi');});
$('[data-cp-tidak]').addEventListener('click',function(){hasil('belum_tercetak');});
$('[data-cp-segar]').addEventListener('click',function(){segar(false);});
$('[data-cp-jalankan]').addEventListener('click',async function(){
 if(busy||(job&&job.status!=='siap'))return;
 var alasan=$('[name=alasan]');if(!job&&alasan.required&&!alasan.value.trim()){pesan('Isi alasan cetak ulang sebelum menyiapkan cetak fisik.');alasan.focus();alasan.reportValidity();return;}
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
   pesan('PDF untuk cetak fisik siap. Buka dokumen dan cetak ke kertas; konfirmasikan setelah hasil fisik diperiksa.');
  }else{
   if(!/text\/xml/i.test(data.headers.get('Content-Type')||''))throw new Error('Perintah printer belum terkonfirmasi.');
   var xml=await data.text();pesan('Mencetak '+rangkap()+' rangkap…');
   try{await window.TeraFlowPrinter.kirim(null,xml);}
   catch(e){
    if(e.belumPasti){pesan(e.message+' Jangan kirim ulang otomatis; periksa kedua rangkap di printer.');return;}
    var gagal=await minta(root.dataset.tujuan+'/'+frozen.kunci+'/hasil',{hasil:'gagal'});await gagal.json();job=null;key='';simpan('kunci','');pesan(e.message+' Tidak dicatat sebagai cetak berhasil.');return;
   }
   pesan('Printer mengonfirmasi berhasil. Menyimpan riwayat…');
   var ack=await minta(root.dataset.tujuan+'/'+frozen.kunci+'/hasil',{hasil:'printer_berhasil'});var j=await ack.json();
   if(j.status!=='berhasil')throw new Error('Riwayat cetak belum terkonfirmasi.');
   simpan('alasan','');segar(true);
  }
 }catch(e){
  pesan(e.message+(sudahKirim?' Periksa hasil fisik; jangan mengirim ulang.':' Isian tetap tersedia.'));
  $('[data-cp-segar]').hidden=false;
 }finally{busy=false;tampilJob();}
});
tampilJob();
return {jalan:function(){$('[data-cp-jalankan]').click();}};
}
window.TeraFlowCetak={pasang:pasang};
pasang(document.querySelector('[data-cetak-halaman]'));
})();
