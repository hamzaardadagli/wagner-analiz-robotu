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
        with st.spinner("Ajan veritabanını ve şemayı analiz ediyor..."):
            try:
                # --- 🤖 AJAN SİSTEMİ VE ARAÇ TANIMLARI (TOOLS) ---
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_database_schema",  # Türkçe karakter kaldırıldı
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
                            "name": "run_sql_query",  # Türkçe karakter kaldırıldı
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
                        "content": "Sen Wagner Kablo üretim veritabanından sorumlu akıllı bir ajansın. Sana verilen araçları (tools) kullanarak kullanıcının sorularını yanıtla. Doğrudan tahmin yürütme, veriyi her zaman araçları kullanarak veritabanından çek. SQL sorgusu üretirken her zaman 'get_database_schema' aracını çağırıp kolon isimlerini kontrol et."
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
                            st.caption(f"⚙️ Ajanın Karar Verdiği Sorgu: `{sql_to_run}`")
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
                    final_response = response_message.content

                # Sonucu ekrana yazdır
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
