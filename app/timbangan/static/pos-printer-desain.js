/* Tampilan penyiapan saja. Pengiriman, ACK, timeout dan audit tetap app.js. */
(() => {
  function init(){
    const root=document.querySelector('[data-pos-printer]');if(!root||root.dataset.ppReady)return;root.dataset.ppReady='1';
    const input=root.querySelector('[name=printer_url]'),save=root.querySelector('[data-simpan-printer]'),check=root.querySelector('[data-periksa-printer]'),print=root.querySelector('[data-cetak]');
    const status=root.querySelector('[data-pp-status]'),result=root.querySelector('[data-pp-result]'),summary=root.querySelector('[data-pp-summary]'),details=root.querySelector('[data-pp-details]'),oldResult=root.querySelector('[data-hasil-cetak]'),report=root.querySelector('[data-laporan-printer]');
    const clean=x=>String(x||'').trim().replace(/\/+$/,'');let committed=input.value,lastAction='',busy=false,lastStatus='Belum diperiksa';
    const dirty=()=>clean(input.value)!==clean(committed);
    function sync(){
      const changed=dirty(),active=window.TeraFlowPrinter.alamat();
      status.textContent=changed?'Alamat belum disimpan':!active?'Alamat belum tersedia':lastStatus;
      root.querySelector('[data-pp-source]').textContent=changed?'Perubahan alamat belum disimpan.':'Alamat printer hanya berlaku pada browser/perangkat ini.';
      root.querySelector('[data-pp-active]').hidden=!changed&&!!input.value;
      root.querySelector('[data-pp-active] [data-alamat-printer]').textContent=active||'(belum disetel)';
      check.disabled=changed||busy;print.setAttribute('aria-disabled',String(changed||busy));save.disabled=busy;input.readOnly=busy;
      save.classList.toggle('halus',!changed);check.classList.toggle('halus',changed);
    }
    function show(text){summary.textContent=text;result.hidden=!text;result.querySelector('[data-pp-next]').hidden=true;result.querySelector('[data-pp-buka-alamat]').hidden=true;}
    function langkah(text,buka=false){const next=result.querySelector('[data-pp-next]');next.textContent=text;next.hidden=!text;const link=result.querySelector('[data-pp-buka-alamat]');link.href=window.TeraFlowPrinter.alamat()||'#';link.hidden=!buka;}
    input.addEventListener('input',()=>{show('');details.hidden=true;sync();});
    // Mencegah pencetakan ke alamat lama ketika ketikan belum disimpan.
    root.addEventListener('click',e=>{
      const action=e.target.closest('[data-simpan-printer],[data-periksa-printer],[data-cetak]');if(!action)return;
      if(busy||(action!==save&&dirty())){e.preventDefault();e.stopImmediatePropagation();return;}
      lastAction=action===save?'alamat':action===check?'pemeriksaan':'cetak';
      show('');details.hidden=true;details.open=false;oldResult.hidden=true;report.hidden=true;
      if(lastAction!=='alamat'){busy=true;lastStatus=lastAction==='cetak'?'Mencetak…':'Memeriksa…';sync();}
    },true);
    document.addEventListener('teraflow:printer',e=>{
      const d=e.detail||{};
      if(d.jenis==='pemeriksaan'){
        busy=false;details.hidden=false;
        const rows=d.hasil||[],service=rows.find(x=>x.judul==='Layanan cetak'),error=rows.find(x=>x.nada==='err');
        if(service?.nada==='ok'){lastStatus='Sambungan berhasil';show('Sambungan berhasil. Cetak uji untuk memeriksa keluaran kertas.');}
        else {
          lastStatus='Sambungan perlu diperiksa';
          if(error?.judul==='Alamat printer'){show('Alamat printer belum disetel di browser ini.');langkah('Isi alamat printer di atas, simpan, lalu periksa sambungan lagi.');}
          else if(error?.judul==='Awalan alamat'){show('Gunakan alamat printer yang diawali https://.');langkah('Perbaiki alamat di atas, simpan, lalu periksa sambungan lagi.');}
          else if(error?.judul==='Izin jaringan lokal'){show('Izin jaringan lokal ditolak.');langkah('Izinkan akses jaringan lokal pada setelan situs di browser, lalu tekan Periksa sambungan lagi.');}
          else if(service?.nada==='err'){show(service.kata||'Printer menolak pemeriksaan.');langkah('Tangani kondisi printer yang disebutkan, lalu tekan Periksa sambungan lagi.');}
          else {show('Printer belum dapat dihubungi.');langkah('Pastikan printer menyala, alamat benar, dan perangkat terhubung ke jaringan pos. Bila perlu, buka alamat printer untuk memeriksa permintaan sertifikat browser, lalu kembali dan periksa lagi.',true);}
        }
      } else if(d.jenis==='hasil'){
        if(!d.pesan)return;
        busy=false;details.hidden=false;
        if(lastAction==='alamat'){
          if(d.nada==='ok'){committed=input.value;lastStatus='Belum diperiksa';show('Alamat disimpan di browser ini. Sambungan belum diperiksa.');}
          else {lastStatus='Alamat belum tersimpan';show('Alamat belum tersimpan. Browser menolak penyimpanan; ketikan tetap tersedia.',true);}
        } else if(lastAction==='cetak'){
          if(d.nada==='ok'){lastStatus='Uji cetak dikonfirmasi';show('Printer mengonfirmasi perintah cetak uji. Periksa kertas yang keluar.');}
          else {lastStatus=d.keadaan?.belumPasti?'Hasil cetak belum pasti':'Printer perlu ditangani';show(d.keadaan?.belumPasti?'Hasil cetak belum dapat dipastikan. Periksa kertas sebelum mengulang agar tidak tercetak dua kali.':d.pesan,true);}
        } else show(d.pesan,d.nada!=='ok');
      }
      sync();
    });
    const dialog=root.querySelector('#pp-petunjuk'),content=root.querySelector('[data-pp-help-content]');
    if(typeof dialog.showModal==='function'){
      root.querySelector('[data-pp-help-slot]').append(content);root.querySelector('[data-pp-help-fallback]').hidden=true;
      root.querySelectorAll('[data-pp-help]').forEach(button=>{button.hidden=false;button.setAttribute('aria-controls',dialog.id);button.setAttribute('aria-haspopup','dialog');button.addEventListener('click',()=>{dialog._opener=button;dialog.showModal();});});

      root.querySelector('[data-pp-close]').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>dialog._opener?.focus());
    }
    // Tombol asli dipindahkan ke baris judul, tidak disalin.
    const title=root.closest('[data-pengaturan]')?.querySelector(':scope>h1'),help=root.querySelector('.pp-heading [data-pp-help]');
    if(title&&help&&!help.hidden){const row=document.createElement('div');row.className='pp-title';title.before(row);row.append(title,help);}
    // Saat kembali dari tab printer (sertifikat/izin), baca ulang status
    // tanpa meminta operator menekan Periksa sambungan. Jangan menimpa ketikan.
    let kembali=false,jadwal;
    document.addEventListener('visibilitychange',()=>{
      if(document.visibilityState==='hidden')kembali=true;
      else if(kembali){kembali=false;periksaKembali();}
    });
    function periksaKembali(){
      clearTimeout(jadwal);jadwal=setTimeout(()=>{
        if(document.visibilityState==='visible'&&!busy&&!dirty()&&window.TeraFlowPrinter.alamat())check.click();
      },200);
    }
    window.addEventListener('online',periksaKembali);
    window.addEventListener('pageshow',e=>{if(e.persisted)periksaKembali();});
    sync();
  }
  if(document.readyState==='complete')init();else document.addEventListener('DOMContentLoaded',init,{once:true});
})();
