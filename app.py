import io
import re
import smtplib
import sqlite3
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
import pandas as pd
import streamlit as st
from openai import OpenAI

matplotlib.use("Agg")  # Arayüzsüz arka plan çizimi için zorunlu ayar
import matplotlib.pyplot as plt

# --- GÜVENLİK & KİMLİK BİLGİLERİ ---
GITHUB_TOKEN = "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"

# E-posta gönderecek hesap bilgi alanları
SENDER_EMAIL = "hamzaardadagli07@gmail.com"  # Gönderici Gmail adresi
SENDER_PASSWORD = (
    "aobn icqf ermd rbtk"  # Google'dan aldığın 16 haneli Uygulama Şifresi
)
RECEIVER_EMAIL = "hamzaardadagli07@gmail.com"  # Raporun gideceği yönetici maili

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


# --- 1. DETAYLI ANALİZ, FORMÜLASYON VE GRAFİK ÜRETİM MOTORU ---
def generate_advanced_manager_report():
    conn = sqlite3.connect("uretim_analiz.db")

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
    # İşlemleri yalnızca son hafta veri çerçevesi (son_hafta_df) üzerinde gerçekleştiriyoruz
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

    # Son Haftanın Günlük Ciro Ortalaması (Genel ortalama yerine bunu kullanıyoruz)
    weekly_daily_totals = son_hafta_df.groupby("TARIH")["CIRO"].sum().reset_index()
    weekly_avg_revenue = weekly_daily_totals["CIRO"].mean()

    # Son Gün Verilerinin Filtrelenmesi
    last_day_date = max_tarih.strftime("%Y-%m-%d")
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

    # Karşılaştırma artık GENEL ortalama ile değil, SON HAFTANIN ortalaması ile yapılıyor
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

    # HTML Şablonu (Son Hafta değerlerine göre biçimlendirilmiş başlıklar)
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
        excel_df = pd.read_excel(uploaded_file)
        excel_df.columns = [c.upper().strip() for c in excel_df.columns]

        conn = sqlite3.connect("uretim_analiz.db")
        excel_df.to_sql("uretim_satis", conn, if_exists="replace", index=False)
        conn.close()

        st.sidebar.success("✅ Excel veritabanına başarıyla aktarıldı!")
        database_ready = True

        # --- ⚡ SİHİRLİ ADIM: OTOMATİK MAİL TETİKLEME ---
        if (
            "last_processed_file" not in st.session_state
            or st.session_state.last_processed_file != uploaded_file.name
        ):
            with st.sidebar.status(
                "🚀 Yeni dosya algılandı! Otomatik son hafta raporu hazırlanıyor...",
                expanded=True,
            ) as status:
                st.write("📈 Son 7 günün X Standart süre ve %85 sınır etkinlik hesabı yapılıyor...")
                report_content, bar_data = generate_advanced_manager_report()

                st.write("📬 Rapor şablonu oluşturuldu. Yöneticiye gönderiliyor...")
                mail_success = send_advanced_report_email(
                    report_content, bar_data
                )

                if mail_success:
                    status.update(
                        label="🚀 Son haftanın raporu başarıyla yöneticiye gönderildi!",
                        state="complete",
                    )
                    st.sidebar.success("📧 Yönetici bilgilendirildi.")
                else:
                    status.update(
                        label="❌ Mail gönderiminde bir sorun oluştu.",
                        state="error",
                    )

            st.session_state.last_processed_file = uploaded_file.name

    except Exception as e:
        st.sidebar.error(f"Dosya işlenirken hata oluştu: {e}")
else:
    try:
        conn = sqlite3.connect("uretim_analiz.db")
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
st.sidebar.write("Gerekirse son hafta raporunu manuel olarak tekrar gönderebilirsiniz.")

if st.sidebar.button("📊 Raporu Yeniden Mail At", key="btn_yonetici_raporu"):
    with st.spinner("Rapor hesaplanıyor ve gönderiliyor..."):
        try:
            report_content, bar_data = generate_advanced_manager_report()
            send_advanced_report_email(report_content, bar_data)
            st.sidebar.success("🚀 Son hafta raporu başarıyla gönderildi!")
            with st.expander("Giden Raporun Önizlemesi", expanded=True):
                st.html(report_content)
        except Exception as e:
            st.sidebar.error(f"Hata: {e}")

st.sidebar.markdown("---")
st.sidebar.markdown("---")

st.sidebar.markdown("""
### 📘 Deneyebileceğiniz Örnek Sorular:
* 📉 *Son 3 yılın en kötü cirolu ayı hangisidir ve toplam ciro ne kadardır?*
* 🏢 *Hangi bölüm (BOLUM) en yüksek ciroyu yaptı?*
* ⚙️ *Toplam üretilen (URETILEN) malzeme adeti ne kadardır?*
* ⚠️ *En çok fire veren ilk 3 bölüm hangisidir?*
* 🔍 *Ortalama ciro miktarımız ne kadardır?*

---
### 🎯 Projenin Amacı & Çalışma Prensibi
Bu sistem; mevcut Excel dosyasındaki verileri analiz eder ve talep edilen başlıklara uygun dinamik gösterge panelleri üreten yapay zeka destekli bir analiz robotudur.
""")

# --- SADE CHATBOT ALANI ---
st.markdown("### 💬 Yapay Zeka Analiz Asistanı")

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
        with st.spinner("Yapay zeka veritabanını analiz ediyor..."):
            try:
                conn = sqlite3.connect("uretim_analiz.db")

                # 💡 AKILLI HARİTALANDIRMA VE TABLO ŞEMASI KORUMASI 💡
                sutun_haritasi, gercek_sutunlar = veritabanı_sutun_haritasi(
                    conn, "uretim_satis"
                )

                # GPT-4o-Mini için şema tanımı
                schema_desc = f"""
                Tablo Adı: uretim_satis
                Tablodaki Gerçek Sütunlar (BÜYÜK/KÜÇÜK HARFE VE TÜRKÇE KARAKTERLERE BİREBİR UYULMALI):
                {', '.join(gercek_sutunlar)}

                KRİTİK EŞLEŞTİRME VE SIRALAMA KURALLARI:
                - Eğer kullanıcı fire, kayıp, kusurlu ürün soruyorsa mutlaka '{sutun_haritasi.get('fire', 'FIRE_MİK')}' sütununu kullan.
                - Sorguda kesinlikle 'FIRE_MİK' sütununu bulamazsan '{sutun_haritasi.get('fire', 'FIRE_MİK')}' karşılığını yaz.
                - 'FIRE_MİK' isminde Türkçe karakter hatası (İ/I uyuşmazlığı) yapma. Veritabanındaki gerçek sütun adı tam olarak budur.
                - ÖNEMLİ (SIRALAMA KURALI): En çok fire verenleri sıralarken 'SUM(CAST({sutun_haritasi.get('fire', 'FIRE_MİK')} AS REAL)) AS TOPLAM_FIRE' kullanarak sayısal sıralama yap.
                - ÖNEMLİ (FİLTRE KURALI): Fire değeri olmayan, null olan veya 0 olan bölümleri listeye almamak için sorguya 'WHERE {sutun_haritasi.get('fire', 'FIRE_MİK')} > 0 AND {sutun_haritasi.get('fire', 'FIRE_MİK')} IS NOT NULL' koşulunu kesinlikle ekle.
                """

                prompt_for_sql = f"""
                Sen bir SQL uzmanısın. Sadece verilen tablo şemasındaki gerçek kolon isimlerini birebir kullanarak geçerli bir SQLite sorgusu yaz.
                Kesinlikle açıklama, yorum veya markdown ekleme.
                
                Veritabanı Şeması ve Kuralları:
                {schema_desc}
                
                Kullanıcı Sorusu: {user_input}
                """

                response = client.chat.completions.create(
                    messages=[
                        {
                            "role": "system",
                            "content": "Sen yardımcı, nesnel ve sadece SQLite kodu dönen profesyonel bir veritabanı asistanısın.",
                        },
                        {"role": "user", "content": prompt_for_sql},
                    ],
                    model="gpt-4o-mini",
                    temperature=0.1,
                )
                sql_response = response.choices[0].message.content.strip()
                sql_query = (
                    sql_response.replace("```sql", "")
                    .replace("```", "")
                    .replace(";", "")
                    .strip()
                )

                if sql_query.upper().count("SELECT") > 1:
                    parts = sql_query.split("SELECT")
                    for part in parts:
                        if part.strip():
                            sql_query = "SELECT " + part.strip()
                            break

                st.caption(f"⚙️ Çalıştırılan SQL Sorgusu: `{sql_query}`")

                query_result = pd.read_sql_query(sql_query, conn)
                conn.close()

                df_string = query_result.to_string()
                is_truncated = False
                if len(query_result) > 30:
                    df_string = query_result.head(30).to_string()
                    is_truncated = True

                prompt_for_answer = f"""
                Kullanıcının sorusuna karşılık veritabanından alınan veri tablosu aşağıdadır.
                Sadece bu verilere dayanarak, kendi yorumunu katmadan tamamen Türkçe ve nesnel bir cevap oluştur.
                Kullanıcı Sorusu: {user_input}
                Veritabanı Sonucu:
                {df_string}
                """

                if is_truncated:
                    prompt_for_answer += "\n\n(Not: Veritabanı çıktısı çok büyük olduğu için sadece ilk 30 satır gönderilmiştir.)"

                response_ans = client.chat.completions.create(
                    messages=[
                        {
                            "role": "system",
                            "content": "Sen yardımcı, nesnel ve Türkçe konuşan bir veritabanı analiz asistanısın.",
                        },
                        {"role": "user", "content": prompt_for_answer},
                    ],
                    model="gpt-4o-mini",
                    temperature=0.1,
                )
                final_response = (
                    response_ans.choices[0].message.content.strip()
                )
                st.write(final_response)

                grafik_kelimeleri = [
                    "grafik",
                    "görselleştir",
                    "çiz",
                    "chart",
                    "plot",
                    "bar",
                    "grafiği",
                ]
                if (
                    any(x in user_input.lower() for x in grafik_kelimeleri)
                    and not query_result.empty
                ):
                    st.info("📊 İstediğiniz analiz için dinamik grafik hazırlanmıştır:")
                    numeric_cols = (
                        query_result.select_dtypes(include=["number"])
                        .columns.tolist()
                    )
                    x_col = query_result.columns[0]
                    if numeric_cols:
                        st.bar_chart(
                            data=query_result, x=x_col, y=numeric_cols[0]
                        )

                if is_truncated:
                    st.dataframe(query_result)

                st.session_state.messages.append(
                    {"role": "assistant", "content": final_response}
                )

            except Exception as e:
                try:
                    conn.close()
                except:
                    pass
                st.error(f"Sorgulama sırasında bir pürüz oluştu. Hata: {e}")