import streamlit as st
import pandas as pd
import sqlite3
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import matplotlib.pyplot as plt
from openai import OpenAI

# --- ⚙️ SAYFA AYARLARI ---
st.set_page_config(page_title="Wagner Kablo - Üretim Analiz Robotu", layout="wide")

# --- 🔒 GÜVENLİK VE KİMLİK BİLGİLERİ (STREAMLIT SECRETS'TAN OKUNUYOR) ---
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    SENDER_PASSWORD = st.secrets["SENDER_PASSWORD"]
except Exception as e:
    # Yerelde test ederken şifrelerin patlamaması için yedek plan:
    GITHUB_TOKEN = "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"
    SENDER_PASSWORD = "aobn icqf ermd rbtk"

SENDER_EMAIL = "hamzaardadagli07@gmail.com"
RECEIVER_EMAIL = "hamzaardadagli07@gmail.com"  # Yönetici e-posta adresi

# --- 🤖 OPENAI (GITHUB MODELS) APİ BAĞLANTISI ---
client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN,
)

# --- 🗄️ VERİTABANI BAĞLANTISI ---
DB_FILE = "production.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uretim (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarih TEXT,
            bolum TEXT,
            uretim_miktari REAL,
            ciro REAL,
            fire_miktari REAL,
            toplam_sure REAL,
            standart_sure REAL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- 📊 GRAFİK VE ANALİZ YARDIMCI FONKSİYONLARI ---
def get_last_7_days_data():
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT * FROM uretim 
        WHERE tarih >= (SELECT date(MAX(tarih), '-7 days') FROM uretim)
        ORDER BY tarih ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def generate_report_and_chart():
    df = get_last_7_days_data()
    if df.empty:
        return None, None, "Veritabanında analiz edilecek son 7 güne ait veri bulunamadı. Lütfen önce sol panelden Excel dosyası yükleyin."
    
    df['tarih_dt'] = pd.to_datetime(df['tarih'])
    gunluk = df.groupby('tarih_dt').agg({
        'ciro': 'sum',
        'standart_sure': 'sum',
        'toplam_sure': 'sum'
    }).reset_index()
    
    gunluk['etkinlik'] = (gunluk['standart_sure'] / gunluk['toplam_sure']) * 100
    
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.bar(gunluk['tarih_dt'].dt.strftime('%d-%m'), gunluk['ciro'], color='skyblue', label='Günlük Ciro (TL)')
    ax1.set_xlabel('Tarih')
    ax1.set_ylabel('Ciro (TL)', color='blue')
    ax1.tick_params(axis='y', labelcolor='blue')
    
    ax2 = ax1.twinx()
    ax2.plot(gunluk['tarih_dt'].dt.strftime('%d-%m'), gunluk['etkinlik'], color='red', marker='o', linewidth=2, label='Etkinlik Oranı (%)')
    ax2.axhline(85, color='gray', linestyle='--', alpha=0.7, label='Kritik Sınır (%85)')
    ax2.set_ylabel('İş Gücü Etkinlik Oranı (%)', color='red')
    ax2.tick_params(axis='y', labelcolor='red')
    
    plt.title('Son 7 Günlük Üretim Ciro ve İş Gücü Etkinlik Analizi')
    fig.tight_layout()
    chart_path = "weekly_report.png"
    plt.savefig(chart_path)
    plt.close()
    
    prompt = f"""
    Aşağıda Wagner Kablo fabrikasına ait son 7 günlük üretim performans verileri yer almaktadır:
    {gunluk.to_string(index=False)}
    
    Bu verileri analiz ederek mühendislik yöneticisi için kısa, profesyonel ve aksiyona dökülebilir bir yönetici özeti raporu hazırla. 
    Özellikle etkinlik oranının %85 kritik sınırının altına düştüğü günlere dikkat çek ve iyileştirme önerilerinde bulun.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        report_text = response.choices[0].message.content
    except Exception as e:
        report_text = f"Yapay zeka analiz raporu oluşturulurken bir hata oluştu: {str(e)}"
        
    return chart_path, report_text, None

def send_email_report(chart_path, report_text):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"Wagner Kablo - Haftalık Üretim Performans Raporu ({datetime.date.today().strftime('%d.%m.%Y')})"
    
    body = f"""
    <html>
      <body>
        <h3>Değerli Yöneticimiz,</h3>
        <p>Mühendislik Departmanı analitik sistemleri tarafından otomatik olarak hazırlanan <strong>Son 7 Günlük Üretim ve İş Gücü Etkinlik Raporu</strong> aşağıda bilgilerinize sunulmuştur:</p>
        <hr/>
        <p style="white-space: pre-line;">{report_text}</p>
        <hr/>
        <h4>Haftalık Performans ve Kritik Sınır Analiz Grafiği:</h4>
        <img src="cid:image1"><br/>
        <p style="font-size: 11px; color: gray;">Bu e-posta sistem tarafından otomatik üretilmiştir.</p>
      </body>
    </html>
    """
    msg.attach(MIMEText(body, 'html'))
    
    with open(chart_path, 'rb') as f:
        img_data = f.read()
    msg_image = MIMEImage(img_data)
    msg_image.add_header('Content-ID', '<image1>')
    msg.attach(msg_image)
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"E-posta gönderilirken hata oluştu: {str(e)}")
        return False

# --- 🖥️ STREAMLIT ARAYÜZ TASARIMI ---
st.title("🏭 Wagner Kablo - Üretim Analiz ve Otomatik Raporlama Sistemi")

# --- ⚙️ SOL PANEL (SIDEBAR) ---
st.sidebar.header("📁 Veri Kaynağı & Yönetim")

uploaded_file = st.sidebar.file_uploader("Üretim Excel Dosyasını Yükleyin (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    try:
        df_uploaded = pd.read_excel(uploaded_file)
        
        # Orijinal sütun isimlerinin birebir doğru olduğunu varsayıyoruz
        df_uploaded['tarih'] = pd.to_datetime(df_uploaded['tarih']).dt.strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(DB_FILE)
        df_uploaded.to_sql("uretim", conn, if_exists="append", index=False)
        conn.close()
        
        st.sidebar.success("Excel veritabanına başarıyla aktarıldı! 🚀")
        
        with st.spinner("Analiz yapılıyor ve yöneticiye e-posta gönderiliyor..."):
            chart, report, err = generate_report_and_chart()
            if not err:
                success = send_email_report(chart, report)
                if success:
                    st.sidebar.info("Haftalık rapor yöneticinize e-posta ile ulaştırıldı! 📬")
            else:
                st.sidebar.warning(err)
            
    except Exception as e:
        st.sidebar.error(f"Excel işlenirken hata oluştu: {str(e)}")

if st.sidebar.button("📊 Raporu Yeniden Mail At"):
    with st.spinner("Rapor hazırlanıyor..."):
        chart, report, err = generate_report_and_chart()
        if not err:
            success = send_email_report(chart, report)
            if success:
                st.sidebar.success("E-posta başarıyla gönderildi! ✅")
                st.markdown("### 📬 Gönderilen Son Rapor Önizlemesi")
                st.image(chart)
                st.write(report)
        else:
            st.sidebar.error(err)

# --- Proje Künyesi ---
st.sidebar.markdown("---")
st.sidebar.info("""
**🎯 Proje Amacı & Altyapısı** Bu sistem; üretim verilerini analiz eden ve iş gücü etkinlik oranlarını hesaplayan yapay zeka destekli bir karar destek robotudur.  
""")

# --- 💬 ANA EKRAN: YAPAY ZEKA SORGULAMA CHAT ARAYÜZÜ ---
st.markdown("""
Bu panel üzerinden üretim veritabanınızla doğal dilde konuşabilirsiniz. Yapay zeka yazdığınız soruyu otomatik olarak SQL'e dökerek veritabanından cevaplayacaktır.
""")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Üretim verileri hakkında bir şey sorun..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        
    with st.chat_message("assistant"):
        with st.spinner("Veritabanı sorgulanıyor..."):
            
            schema_info = """
            Veritabanı tablosu adı 'uretim'dir.
            Sütunlar:
            - tarih (TEXT, YYYY-MM-DD)
            - bolum (TEXT)
            - uretim_miktari (REAL)
            - ciro (REAL)
            - fire_miktari (REAL)
            - toplam_sure (REAL)
            - standart_sure (REAL)
            
            SQLite biçiminde sadece geçerli bir SQL kodu üret, açıklama yazma.
            """
            
            ai_prompt = f"""
            Şemaya göre kullanıcının sorusuna cevap verecek SQL sorgusunu yaz:
            Şema: {schema_info}
            Kullanıcı Sorusu: {prompt}
            """
            
            try:
                sql_response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": ai_prompt}],
                    temperature=0.1
                )
                generated_sql = sql_response.choices[0].message.content.strip().replace("```sql", "").replace("```", "")
                
                conn = sqlite3.connect(DB_FILE)
                query_result = pd.read_sql_query(generated_sql, conn)
                conn.close()
                
                interpretation_prompt = f"""
                Kullanıcının sorusu: {prompt}
                Veritabanından dönen sorgu sonucu:
                {query_result.to_string()}
                
                Kullanıcıya Türkçe, teknik bir yanıt yaz.
                """
                
                final_response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": interpretation_prompt}],
                    temperature=0.5
                )
                answer = final_response.choices[0].message.content
                
                st.markdown(answer)
                st.dataframe(query_result)
                
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
            except Exception as e:
                error_msg = f"Sorgulama sırasında bir hata oluştu: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
