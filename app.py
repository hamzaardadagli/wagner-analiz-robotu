import io
import re
import smtplib
import sqlite3
import json
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
import pandas as pd
import streamlit as st
from openai import OpenAI

matplotlib.use("Agg")  # Arayüzsüz arka plan çizimi için zorunlu ayar
import matplotlib.pyplot as plt

# --- 🔒 GÜVENLİK VE KİMLİK BİLGİLERİ ---
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    SENDER_PASSWORD = st.secrets["SENDER_PASSWORD"]
except Exception as e:
    st.error("⚠️ Streamlit Secrets ayarları eksik! GITHUB_TOKEN ve SENDER_PASSWORD tanımlı olmalıdır.")
    st.stop()

# E-posta gönderecek hesap bilgi alanları
SENDER_EMAIL = "hamzaardadagli07@gmail.com"  # Gönderici Gmail adresi
RECEIVER_EMAIL = "hamzaardadagli07@gmail.com"  # Raporun gideceği yönetici maili
DB_NAME = "uretim_analiz.db"  # Tüm sistemde ortak kullanılacak veritabanı ismi

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN,
)


# --- 🛠️ TÜRKÇE KARAKTER & AKILLI SÜTUN EŞLEŞTİRME YARDIMCILARI ---
def turkce_karakter_temizle(metin):
    """Karakter uyuşmazlıklarını çözmek için metni İngilizce karakterlere normalize eder."""
    metin = metin.lower().strip()
    karakterler = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
        "İ": "i",
    }
    for tr, eng in karakterler.items():
        metin = metin.replace(tr, eng)
    return re.sub(r"[^a-z0-9_]", "", metin)


def veritabanı_sutun_haritasi(conn, tablo_adi="uretim_satis"):
    """Tablodaki gerçek sütun adlarını okuyarak temizlenmiş karşılıklarıyla eşleştirir."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({tablo_adi})")
    gercek_sutunlar = [info[1] for info in cursor.fetchall()]

    harita = {}
    for sutun in gercek_sutunlar:
        temiz = turkce_karakter_temizle(sutun)
        harita[temiz] = sutun
        if "fire" in temiz:
            harita["fire"] = sutun
            harita["fire_mik"] = sutun
            harita["fire_miktari"] = sutun
    return harita, gercek_sutunlar


# --- 🛠️ AJAN KULLANIMI İÇİN ARKA PLAN FONKSİYONLARI (TOOLS) ---
def sql_sorgusu_calistir(sql_query):
    """Veritabanında güvenli bir şekilde SQL sorgusu çalıştırır ve sonuçları döner."""
    try:
        conn = sqlite3.connect(DB_NAME)
        # Güvenlik Kontrolü: Sadece veri okuma (SELECT) sorgularına izin verilir
        cleaned_query = sql_query.strip().upper()
        if not cleaned_query.startswith("SELECT"):
            conn.close()
            return {"error": "Güvenlik uyarısı: Sadece veri okuma (SELECT) sorguları çalıştırılabilir."}
            
        df = pd.read_sql_query(sql_query, conn)
        conn.close()
        return df.to_dict(orient="records")  # LLM'in rahat okuyabilmesi için JSON benzeri yapı
    except Exception as e:
        return {"error": f"Sorgu çalıştırılırken hata oluştu: {str(e)}"}


def veritabanı_semasını_getir():
    """Veritabanındaki uretim_satis tablosunun şemasını, kolonlarını ve haritalandırma kurallarını döner."""
    try:
        conn = sqlite3.connect(DB_NAME)
        sutun_haritasi, gercek_sutunlar = veritabanı_sutun_haritasi(conn, "uretim_satis")
        conn.close()
        
        # Gerçek veritabanındaki sütunların listesini çıkarıp büyük/küçük harf esnekliğini de ekleyelim
        ciro_sutunu = next((col for col in gercek_sutunlar if "CIRO" in col.upper() or "KAZANC" in col.upper()), "CIRO")
        fire_sutunu = next((col for col in gercek_sutunlar if "FIRE" in turkce_karakter_temizle(col) or "ISKARTA" in turkce_karakter_temizle(col)), "FIRE_MIK")
        bolum_sutunu = next((col for col in gercek_sutunlar if "BOLUM" in turkce_karakter_temizle(col) or "DEPARTMAN" in turkce_karakter_temizle(col)), "BOLUM")
        uretilen_sutunu = next((col for col in gercek_sutunlar if "URETILEN" in col.upper() or "MIKTAR" in col.upper()), "URETILEN")

        return {
            "tablo_adi": "uretim_satis",
            "gercek_kolonlar": gercek_sutunlar,
            "kolon_haritalama_ipuclari": {
                "ciro_kolonu": f"Ciro, ciro miktarı veya kazanç sorgularında veritabanındaki gerçek sütun adı: '{ciro_sutunu}'",
                "fire_kolonu": f"Fire, ıskarta, hurda miktarı veya kalite kayıpları sorgularında veritabanındaki gerçek sütun adı: '{fire_sutunu}'",
                "bolum_kolonu": f"Bölüm, hat, departman sorgularında veritabanındaki gerçek sütun adı: '{bolum_sutunu}'",
                "uretilen_kolonu": f"Üretilen miktar, üretim adeti sorgularında veritabanındaki gerçek sütun adı: '{uretilen_sutunu}'"
            },
            "kritik_kurallar": {
                "siralama_kurali": f"En çok fire verenleri sıralarken 'SUM(CAST({fire_sutunu} AS REAL)) AS TOPLAM_FIRE' kullanarak sayısal sıralama yapın.",
                "filtre_kurali": f"Boş ve sıfır fireli alanları dışarıda bırakmak için 'WHERE {fire_sutunu} > 0 AND {fire_sutunu} IS NOT NULL' koşulunu ekleyin."
            }
        }
    except Exception as e:
        return {"error": f"Şema okunurken hata oluştu: {str(e)}"}


# --- 1. DETAYLI ANALİZ, FORMÜLASYON VE GRAFİK ÜRETİM MOTORU ---
def generate_advanced_manager_report():
    conn = sqlite3.connect(DB_NAME)

    # Sütun haritasını çıkararak dinamik sütun belirleyelim
    sutun_haritasi, gercek_sutunlar = veritabanı_sutun_haritasi(
        conn, "uretim_satis"
    )

    df = pd.read_sql_query("SELECT * FROM uretim_satis", conn)
    conn.close()

    df.columns = [c.upper().strip() for c in df.columns]

    # Tarih formatlama ve sıralama
    if "TARIH" in df.columns:
        df["TARIH"] = pd.to_datetime(df["TARIH"])
        df = df.sort_values(by="TARIH")
    elif "GUN" in df.columns:
        df["TARIH"] = pd.to_datetime(df["GUN"])
        df = df.sort_values(by="TARIH")

    # --- ⏳ SON HAFTANIN (SON 7 GÜN) FİLTRELENMESİ ---
    max_tarih = df["TARIH"].max()
    baslangic_tarihi = max_tarih - pd.Timedelta(days=6)  # Son 7 gün (en son gün dahil)
    son_hafta_df = df[(df["TARIH"] >= baslangic_tarihi) & (df["TARIH"] <= max_tarih)]

    # --- 🧮 X STANDART SÜRE VE ETKİNLİK FORMÜLASYONU ---
    if (
        "LOGOKESIMSURE" in son_hafta_df.columns
        and "LOGOMONTAJSURE" in son_hafta_df.columns
        and "URETILEN" in son_hafta_df.columns
    ):
        son_hafta_df = son_hafta_df.copy()
        son_hafta_df["X_STANDART_SURE"] = (
            (son_hafta_df["LOGOKESIMSURE"] + son_hafta_df["LOGOMONTAJSURE"]) * son_hafta_df["URETILEN"]
        ) / 60
        son_hafta_df["ETKINLIK_DEGERI"] = (
            son_hafta_df["X_STANDART_SURE"] / son_hafta_df["TOPLAM_ADAM_SAAT"]
        ) * 100
    else:
        son_hafta_df = son_hafta_df.copy()
        son_hafta_df["X_STANDART_SURE"] = son_hafta_df["TOPLAM_ADAM_SAAT"] * 0.82
        son_hafta_df["ETKINLIK_DEGERI"] = 82.0

    # Son Haftanın Günlük Ciro Ortalaması
    weekly_daily_totals = son_hafta_df.groupby("TARIH")["CIRO"].sum().reset_index()
    weekly_avg_revenue = weekly_daily_totals["CIRO"].mean()

    # Son Gün Verilerinin Filtrelenmesi
    last_day_df = son_hafta_df[son_hafta_df["TARIH"] == max_tarih]

    # Dinamik Fire Sütunu Tespiti
    fire_sutun_adi = (
        sutun_haritasi.get("fire", "FIRE_MIK").upper().strip()
    )

    # Son Günün Değerleri
    last_day_production = (
        last_day_df["URETILEN"].sum() if "URETILEN" in last_day_df.columns else 0
    )
    
    if fire_sutun_adi in last_day_df.columns:
        last_day_scrap = pd.to_numeric(last_day_df[fire_sutun_adi], errors='coerce').sum()
    else:
        last_day_scrap = 0
        
    last_day_hours = (
        last_day_df["TOPLAM_ADAM_SAAT"].sum()
        if "TOPLAM_ADAM_SAAT" in last_day_df.columns
        else 0
    )
    last_day_revenue = (
        last_day_df["CIRO"].sum() if "CIRO" in last_day_df.columns else 0
    )

    last_day_standart_hours = last_day_df["X_STANDART_SURE"].sum()
    last_day_efficiency = (
        (last_day_standart_hours / last_day_hours * 100)
        if last_day_hours > 0
        else 0
    )

    last_day_financial_efficiency = (
        (last_day_revenue / last_day_hours) if last_day_hours > 0 else 0
    )
    last_day_operational_efficiency = (
        (last_day_production / last_day_hours) if last_day_hours > 0 else 0
    )
    last_day_scrap_rate = (
        (last_day_scrap / last_day_production * 100)
        if last_day_production > 0
        else 0
    )

    if last_day_efficiency >= 85:
        efficiency_status_html = (
            "<span style='color: #2f855a; font-weight: bold;'>🟢 Olumlu / İyi</span>"
        )
        efficiency_box_style = "color: #2f855a; background-color: #f0fff4; border-left: 4px solid #38a169;"
        efficiency_feedback = f"Standartlara uygun ve verimli çalışılmıştır. Günlük iş gücü kullanım etkinlik oranınız (%{last_day_efficiency:.1f}) hedef limitin (%85) üzerindedir."
    else:
        efficiency_status_html = "<span style='color: #c53030; font-weight: bold;'>🔴 Gözden Geçirilmeli</span>"
        efficiency_box_style = "color: #c53030; background-color: #fff5f5; border-left: 4px solid #e53e3e;"
        efficiency_feedback = f"Üretimde hedeflenen standart sürenin gerisinde kalınmıştır. Günlük etkinlik oranınız (%{last_day_efficiency:.1f}) kritik sınırın (%85) altındadır."

    # Karşılaştırma
    difference_percentage = (
        (last_day_revenue - weekly_avg_revenue) / weekly_avg_revenue
    ) * 100
    if last_day_revenue >= weekly_avg_revenue:
        ciro_feedback_style = "color: #2b6cb0; background-color: #ebf8ff; border-left: 4px solid #3182ce;"
        ciro_feedback_text = f"🔵 <b>Son Gün Ciro Analizi:</b> Son gün gerçekleşen ciro ({last_day_revenue:,.2f} TL/€), <b>son haftanın günlük ciro ortalamasının ({weekly_avg_revenue:,.2f} TL/€)</b> <b>%{difference_percentage:.1f} üzerinde</b> karlı bir şekilde kapatılmıştır."
    else:
        ciro_feedback_style = "color: #744210; background-color: #fffaf0; border-left: 4px solid #dd6b20;"
        ciro_feedback_text = f"🟠 <b>Son Gün Ciro Analizi:</b> Son gün gerçekleşen ciro ({last_day_revenue:,.2f} TL/€), <b>son haftanın günlük ciro ortalamasının ({weekly_avg_revenue:,.2f} TL/€)</b> <b>%{abs(difference_percentage):.1f} altında</b> kalmıştır."

    # Son Haftanın En Yüksek Ciro Günü
    max_revenue_row = weekly_daily_totals.loc[weekly_daily_totals["CIRO"].idxmax()]
    max_revenue_date = max_revenue_row["TARIH"].strftime("%Y-%m-%d")
    max_revenue_val = max_revenue_row["CIRO"]

    # Son Haftanın En Çok Üretilen Malzemesi
    son_hafta_sorted_by_production = son_hafta_df.sort_values(by="URETILEN", ascending=False)
    most_produced_material = (
        son_hafta_sorted_by_production["MALZEME_KOD"].iloc[0]
        if "MALZEME_KOD" in son_hafta_sorted_by_production.columns
        else "Bilinmiyor"
    )
    most_produced_amount = (
        son_hafta_sorted_by_production["URETILEN"].iloc[0]
        if "URETILEN" in son_hafta_sorted_by_production.columns
        else 0
    )

    # Son Haftanın Bölüm Bazlı Toplam Ciroları
    revenue_by_section = son_hafta_df.groupby("BOLUM")["CIRO"].sum().reset_index()
    section_rows_html = ""
    for _, row in revenue_by_section.iterrows():
        section_rows_html += f"<tr><td>{row['BOLUM']}</td><td style='font-weight: bold;'>{row['CIRO']:,.2f}</td></tr>"

    # --- 📈 ÇUBUK GRAFİĞİ ÜRETİMİ (SADECE SON 7 GÜN) ---
    daily_efficiency = (
        son_hafta_df.groupby("TARIH")
        .apply(
            lambda x: (
                x["X_STANDART_SURE"].sum() / x["TOPLAM_ADAM_SAAT"].sum() * 100
            )
            if x["TOPLAM_ADAM_SAAT"].sum() > 0
            else 0
        )
        .reset_index(name="GUNLUK_ETKINLIK")
    )

    bar_labels = daily_efficiency["TARIH"].dt.strftime("%d-%m-%Y").tolist()
    bar_values = daily_efficiency["GUNLUK_ETKINLIK"].tolist()

    plt.figure(figsize=(6, 4))
    colors_bar = ["#38a169" if val >= 85 else "#e53e3e" for val in bar_values]

    bars = plt.bar(bar_labels, bar_values, color=colors_bar, width=0.5)
    plt.axhline(
        y=85,
        color="#d69e2e",
        linestyle="--",
        linewidth=1.5,
        label="Kritik Limit (%85)",
    )

    for bar in bars:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + 2,
            f"%{height:.1f}",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )

    plt.title(
        "Son Haftalık İş Gücü Etkinlik Trendi (%)", fontsize=11, fontweight="bold", pad=15
    )
    plt.ylabel("Etkinlik Oranı (%)", fontsize=9)
    plt.ylim(0, max(max(bar_values) + 15, 110))
    plt.legend(loc="lower left", fontsize=8)
    plt.tight_layout()

    bar_img_buf = io.BytesIO()
    plt.savefig(bar_img_buf, format="png", dpi=100)
    bar_img_buf.seek(0)
    plt.close()

    # HTML Şablonu
    report_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #1a365d; border-bottom: 2px solid #2b6cb0; padding-bottom: 10px; margin-bottom: 20px;">📊 Güncel Haftalık Yönetici Performans ve Etkinlik Raporu</h2>
        <div style="padding: 15px; border-radius: 5px; margin-bottom: 15px; {efficiency_box_style}">
            <h4 style="margin: 0 0 5px 0;">🎯 Son Gün Etkinlik Skoru: %{last_day_efficiency:.1f} - {efficiency_status_html}</h4>
            <p style="margin: 0; font-size: 14px;">{efficiency_feedback}</p>
        </div>
        <div style="padding: 12px; border-radius: 5px; margin-bottom: 25px; {ciro_feedback_style}">
            <p style="margin: 0; font-size: 13px;">{ciro_feedback_text}</p>
        </div>
        <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%; text-align: left; border: 1px solid #ddd; margin-bottom: 25px;">
            <tr style="background-color: #2d3748; color: white;">
                <th style="width: 40%;">Metrik / Gösterge</th>
                <th style="width: 30%;">Hesaplama Yöntemi / Formülü</th>
                <th style="width: 30%;">Son Gün Gerçekleşen Değeri</th>
            </tr>
            <tr style="background-color: #f7fafc; font-weight: bold;">
                <td>⚡ İş Gücü Etkinlik Oranı</td>
                <td>(Standart Süre / Toplam Adam Saat) * 100</td>
                <td>%{last_day_efficiency:.1f} ({efficiency_status_html})</td>
            </tr>
            <tr>
                <td>1. Finansal Verimlilik</td>
                <td>Ciro / Adam-Saat</td>
                <td style="font-weight: bold; color: #2b6cb0;">{last_day_financial_efficiency:,.2f} / Saat</td>
            </tr>
            <tr>
                <td>2. Operasyonel Verimlilik</td>
                <td>Üretilen Adet / Adam-Saat</td>
                <td style="font-weight: bold; color: #3182ce;">{last_day_operational_efficiency:,.1f} Adet / Saat</td>
            </tr>
            <tr>
                <td>3. Kalite Verimliliği (Fire Oranı)</td>
                <td>(Fire Miktarı / Üretilen Miktar) * 100</td>
                <td style="color: #c53030; font-weight: bold;">%{last_day_scrap_rate:.2f}</td>
            </tr>
        </table>
        <h3 style="color: #2b6cb0; margin-bottom: 10px;">📉 Son 7 Günün Önemli Performans Göstergeleri (KPI)</h3>
        <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%; text-align: left; border: 1px solid #ddd; margin-bottom: 25px;">
            <tr style="background-color: #2b6cb0; color: white;">
                <th style="width: 40%;">Analiz Kriteri</th>
                <th style="width: 30%;">İlişkili Tarih / Malzeme Kodu</th>
                <th style="width: 30%;">Gerçekleşen Değer (Son Hafta)</th>
            </tr>
            <tr>
                <td><b>Haftanın En Yüksek Cirosu</b></td>
                <td>Tarih: {max_revenue_date}</td>
                <td style="color: #2f855a; font-weight: bold;">{max_revenue_val:,.2f}</td>
            </tr>
            <tr>
                <td><b>Haftanın En Çok Üretilen Malzemesi</b></td>
                <td>Kod: <b>{most_produced_material}</b></td>
                <td style="font-weight: bold;">{most_produced_amount:,.0f} Adet</td>
            </tr>
        </table>
        <table border="0" cellpadding="0" cellspacing="0" style="width: 100%;">
            <tr>
                <td style="width: 50%; padding-right: 15px; vertical-align: top;">
                    <h3 style="color: #2b6cb0; margin-top: 0; margin-bottom: 10px;">🏢 Son Haftanın Bölüm Bazlı Ciro Dağılımı</h3>
                    <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%; text-align: left; border: 1px solid #ddd;">
                        <tr style="background-color: #4a5568; color: white;">
                            <th>Bölüm Adı</th>
                            <th>Toplam Ciro</th>
                        </tr>
                        {section_rows_html}
                    </table>
                </td>
                <td style="width: 50%; padding-left: 15px; vertical-align: top; text-align: center;">
                    <h3 style="color: #2b6cb0; margin-top: 0; margin-bottom: 10px;">📊 Haftalık Etkinlik Trendi</h3>
                    <img src="cid:bar_chart" width="400" style="border: 1px solid #ddd; border-radius: 8px; padding: 10px; background-color: #fff;"/>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    return report_html, bar_img_buf.getvalue()


def send_advanced_report_email(html_content, bar_png):
    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = "📊 Son Haftanın Yönetici Raporu ve İş Gücü Etkinlik Analizi"
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECEIVER_EMAIL

        msgAlternative = MIMEMultipart("alternative")
        msg.attach(msgAlternative)
        part_html = MIMEText(html_content, "html", "utf-8")
        msgAlternative.attach(part_html)

        img_bar = MIMEImage(bar_png)
        img_bar.add_header("Content-ID", "<bar_chart>")
        msg.attach(img_bar)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        # Secrets'tan gelen şifre doğrudan kullanılıyor
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.sidebar.error(f"E-posta otomatik olarak gönderilemedi: {e}")
        return False


# --- STREAMLIT ARAYÜZÜ ---
st.set_page_config(page_title="Üretim & Ciro Analiz Robotu (AI)", layout="wide")
st.title("🤖 GitHub & GPT-4o-Mini Destekli Analiz Robotu")

# --- 🚀 AKILLI OTOMATİK SÜRÜKLE-BIRAK ALANI ---
st.sidebar.markdown("# 📁 Veri Kaynağı Güncelleme")
uploaded_file = st.sidebar.file_uploader(
    "Wagner Kablo Excel Dosyasını Yükleyin", type=["xlsx", "xls"]
)

database_ready = False

if uploaded_file is not None:
    try:
        is_new_file = False
        if "last_processed_file" not in st.session_state:
            st.session_state.last_processed_file = ""
            is_new_file = True
        elif st.session_state.last_processed_file != uploaded_file.name:
            is_new_file = True

        excel_df = pd.read_excel(uploaded_file)
        excel_df.columns = [c.upper().strip() for c in excel_df.columns]

        conn = sqlite3.connect(DB_NAME)
        excel_df.to_sql("uretim_satis", conn, if_exists="replace", index=False)
        conn.close()

        st.sidebar.success("✅ Excel veritabanına başarıyla aktarıldı!")
        database_ready = True

        # --- ⚡ KESİN OTOMATİK MAİL TETİKLEME ---
        if is_new_file:
            with st.sidebar.status("🚀 Yeni dosya algılandı! Rapor gönderiliyor...", expanded=True) as status:
                report_content, bar_data = generate_advanced_manager_report()
                mail_success = send_advanced_report_email(report_content, bar_data)

                if mail_success:
                    status.update(
                        label="🚀 Rapor başarıyla yöneticiye gönderildi!",
                        state="complete",
                    )
                    st.sidebar.success("📧 Yönetici bilgilendirildi.")
                    st.session_state.last_processed_file = uploaded_file.name
                else:
                    status.update(
                        label="❌ Rapor gönderilemedi.",
                        state="error",
                    )
                    st.session_state.last_processed_file = ""

    except Exception as e:
        st.sidebar.error(f"Dosya işlenirken hata oluştu: {e}")
else:
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='uretim_satis'"
        )
        if cursor.fetchone():
            database_ready = True
        conn.close()
    except:
        pass

if not database_ready:
    st.info(
        "💡 Lütfen sisteme başlamak için sol panelden güncel üretim Excel dosyasını sürükleyip bırakın."
    )
    st.stop()

# --- YÖNETİCİ MANUEL RAPOR PANELİ ---
st.sidebar.markdown("---")
st.sidebar.markdown("# ⚙️ Manuel Kontrol Paneli")

if st.sidebar.button("📊 Raporu Yeniden Mail At", key="btn_yonetici_raporu"):
    with st.spinner("Rapor hesaplanıyor ve gönderiliyor..."):
        try:
            report_content, bar_data = generate_advanced_manager_report()
            if send_advanced_report_email(report_content, bar_data):
                st.sidebar.success("🚀 Rapor başarıyla gönderildi!")
                with st.expander("Giden Raporun Önizlemesi", expanded=True):
                    st.html(report_content)
        except Exception as e:
            st.sidebar.error(f"Hata: {e}")

st.sidebar.markdown("---")

st.sidebar.markdown("""
### 📘 Deneyebileceğiniz Örnek Sorular:
* 📉 *Son 3 yılın en kötü cirolu ayı hangisidir?*
* 🏢 *Hangi bölüm (BOLUM) en yüksek ciroyu yaptı?*
* ⚙️ *Toplam üretilen (URETILEN) malzeme adeti ne kadardır?*
* ⚠️ *En çok fire veren ilk 3 bölüm hangisidir?*

---
### 🎯 Projenin Çalışma Prensibi
Sistem, yüklenen Excel verilerini SQLite veritabanında arşivler ve yapay zeka aracılığıyla dilediğiniz analizleri yapmanızı sağlar.
""")


# --- SADE CHATBOT ALANI ---
st.markdown("### 💬 Yapay Zeka Analiz Asistanı (Ajan Modu)")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

user_input = st.chat_input(
    "Üretim ve ciro verileri hakkında net bir soru sorun..."
)
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Ajan veritabanını analiz ediyor..."):
            try:
                # --- 🤖 AJAN SİSTEMİ VE ARAÇ TANIMLARI (TOOLS) ---
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_database_schema",
                            "description": "Veritabanındaki tabloları, kolon isimlerini ve hangi kolonun ne anlama geldiğini öğrenmek için bu fonksiyonu çağır.",
                            "parameters": {
                                "type": "object",
                                "properties": {}
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "run_sql_query",
                            "description": "Oluşturulan geçerli SQLite SELECT sorgusunu veritabanında çalıştırıp sonuçları almak için bu fonksiyonu kullan.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "sql_query": {
                                        "type": "string",
                                        "description": "Çalıştırılacak geçerli SQLite sorgusu. Örn: SELECT * FROM uretim_satis LIMIT 5"
                                    }
                                },
                                "required": ["sql_query"]
                            }
                        }
                    }
                ]

                # Ajanın karar döngüsü için başlangıç geçmişi
                agent_messages = [
                    {
                        "role": "system",
                        "content": "Sen Wagner Kablo üretim veritabanından sorumlu akıllı bir ajansın. Sana verilen araçları (tools) kullanarak kullanıcının sorularını yanıtla. Teknik detayları, SQL kodlarını veya hangi aracı çalıştıracağını asla kullanıcıya söyleme. Doğrudan veritabanından aldığın verileri yorumlayıp nihai Türkçe cevabı ver."
                    },
                    {"role": "user", "content": user_input}
                ]

                # 1. Aşama: LLM'e soruyu ve araçları gönderiyoruz
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=agent_messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1
                )

                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                query_result_for_chart = pd.DataFrame()  # Dinamik grafik çizimi için boş df

                # Eğer araç çağrısı varsa arka planda işletiyoruz
                if tool_calls:
                    agent_messages.append(response_message)  # LLM'in kararını geçmişe ekle

                    # Çağrılmak istenen tüm araçları sırayla çalıştır
                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)

                        # Aracı tetikleme
                        if function_name == "get_database_schema":
                            tool_output = veritabanı_semasını_getir()
                        elif function_name == "run_sql_query":
                            sql_to_run = function_args.get("sql_query")
                            tool_output = sql_sorgusu_calistir(sql_to_run)
                            
                            # Grafik çizimi ihtimaline karşı veriyi pandas dataframe'e alalım
                            if isinstance(tool_output, list) and len(tool_output) > 0:
                                query_result_for_chart = pd.DataFrame(tool_output)
                        else:
                            tool_output = {"error": "Bilinmeyen fonksiyon."}

                        # Fonksiyonun sonucunu LLM geçmişine ekliyoruz
                        agent_messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(tool_output)
                        })

                    # 2. Aşama: Elde edilen verilerle LLM'e tekrar gidip nihai cevabı ürettiriyoruz
                    second_response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=agent_messages,
                        temperature=0.1
                    )
                    final_response = second_response.choices[0].message.content
                else:
                    # Eğer doğrudan bir araç kullanmaya gerek duymadıysa gelen cevabı alıyoruz
                    final_response = response_message.content

                # Sadece ve sadece nihai sonucu ekrana basıyoruz (Ara/geçici metinler asla yazdırılmaz)
                st.write(final_response)

                # Dinamik Grafik Çizimi (Eğer kullanıcı grafik istediyse ve verimiz varsa)
                grafik_kelimeleri = ["grafik", "görselleştir", "çiz", "chart", "plot", "bar"]
                if (
                    any(x in user_input.lower() for x in grafik_kelimeleri)
                    and not query_result_for_chart.empty
                ):
                    st.info("📊 İstediğiniz analiz için dinamik grafik hazırlanmıştır:")
                    numeric_cols = (
                        query_result_for_chart.select_dtypes(include=["number"])
                        .columns.tolist()
                    )
                    x_col = query_result_for_chart.columns[0]
                    if numeric_cols:
                        st.bar_chart(
                            data=query_result_for_chart, x=x_col, y=numeric_cols[0]
                        )

                # Geçmişe kaydet
                st.session_state.messages.append(
                    {"role": "assistant", "content": final_response}
                )

            except Exception as e:
                st.error(f"Sorgulama sırasında bir pürüz oluştu. Hata: {e}")
