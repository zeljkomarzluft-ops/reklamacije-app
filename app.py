import streamlit as st
import sqlite3
import json
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
import datetime
import fitz  # PyMuPDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- POSTAVKE STRANICE ---
st.set_page_config(
    page_title="Upravljanje Reklamacijama - Elgrad",
    page_icon="📋",
    layout="wide"
)

# --- BAZA PODATAKA (SQLite) ---
def init_db():
    conn = sqlite3.connect("reklamacije.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS reklamacije (
            id TEXT PRIMARY KEY,
            broj_naloga TEXT,
            zadnjih_6 TEXT,
            kupac TEXT,
            dekor TEXT,
            komada INTEGER,
            status TEXT,
            vraceni_komadi TEXT,
            nacrt_pdf BLOB,
            otpremnica_pdf BLOB,
            datum_kreiranja TEXT,
            log_promjena TEXT,
            broj_otpremnice TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE reklamacije ADD COLUMN broj_otpremnice TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

init_db()

# --- POMOĆNE FUNKCIJE ---
def dodaj_log(postojeci_log_json, poruka):
    logovi = json.loads(postojeci_log_json) if postojeci_log_json else []
    vrijeme = datetime.datetime.now().strftime("%d.%m.%Y. %H:%M:%S")
    logovi.append(f"[{vrijeme}] {poruka}")
    return json.dumps(logovi, ensure_ascii=False)

def posalji_email_obavijest(broj_naloga, kupac, status_povrata):
    try:
        SMTP_SERVER = st.secrets["email"]["smtp_server"]
        SMTP_PORT = int(st.secrets["email"]["smtp_port"])
        SENDER_EMAIL = st.secrets["email"]["sender_email"]
        SENDER_PASSWORD = st.secrets["email"]["sender_password"]
        RECEIVER_EMAIL = st.secrets["email"]["receiver_email"]

        predmet = f"Obavijest o povratu reklamacije: Nalog {broj_naloga} - {status_povrata}"
        tijelo = f"""
        Pozdrav,

        Izdavač u skladištu je ažurirao status povrata reklamacije.

        • Broj naloga: {broj_naloga}
        • Kupac: {kupac}
        • Status povrata komada: {status_povrata}
        • Vrijeme promjene: {datetime.datetime.now().strftime('%d.%m.%Y. u %H:%M')}

        Ova poruka je automatski generirana iz sustava za reklamacije.
        """

        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = predmet
        msg.attach(MIMEText(tijelo, 'plain', 'utf-8'))

        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)

        return True
    except Exception as e:
        st.warning(f"Sustav nije uspio poslati e-mail obavijest: {e}")
        return False

def generiraj_jednostrani_pdf(nacrt_bytes, broj_naloga, kupac, dekor, komada, broj_otpremnice):
    """Generira jedan A4 PDF s preslikom nacrta, napomenom i podrškom za hrvatska slova."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # 1. Zaglavlje (uz uredan ispis broja otpremnice i imena s HR znakovima)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, height - 35, "ELGRAD d.o.o. - POTVRDA REKLAMACIJE I POVRATA")
    
    c.setFont("Helvetica", 10)
    otpr_tekst = f" | Otpremnica: {broj_otpremnice}" if broj_otpremnice else " | Otpremnica: Nije unesena"
    c.drawString(40, height - 52, f"Radni nalog: {broj_naloga}{otpr_tekst}")
    c.drawString(40, height - 67, f"Kupac: {kupac}   |   Stavka: {dekor} ({komada} kom)   |   Datum: {datetime.date.today().strftime('%d.%m.%Y.')}")
    c.line(40, height - 73, width - 40, height - 73)

    # 2. Slika Nacrta
    try:
        doc_nacrt = fitz.open(stream=nacrt_bytes, filetype="pdf")
        page = doc_nacrt[0]
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        img_reader = ImageReader(io.BytesIO(img_bytes))
        c.drawImage(img_reader, 40, 160, width=515, height=580, preserveAspectRatio=True)
    except Exception:
        c.drawString(40, height / 2, "[Nije moguće prikazati vizualni nacrt]")

    # 3. Dno stranice: Napomena i Potpis
    c.line(40, 150, width - 40, 150)
    c.rect(40, 80, width - 80, 60, fill=0)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(50, 128, "NAPOMENA O PREUZIMANJU I POVRATU REKLAMIRANOG MATERIJALA:")
    c.setFont("Helvetica", 8)
    c.drawString(50, 114, "• Kupac preuzima nove/zamjenske komade specificirane u dokumentu u potpunosti ispravne.")
    c.drawString(50, 101, f"• NAPOMENA: Kupac je prilikom preuzimanja vratio sve reklamirane komade ({komada} kom - {dekor}).")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(50, 88, "[  ] KUPAC JE VRATIO SVE KOMADE            [  ] KUPAC NIJE VRATIO SVE KOMADE")

    c.setFont("Helvetica", 9)
    c.drawString(50, 40, "Preuzeo kupac (potpis): _______________________")
    c.drawString(320, 40, "Izdano / Potvrdio (potpis): _______________________")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

# --- NAVIGACIJA / IZBORNIK ---
st.sidebar.title("📋 Sustav Reklamacija")
uloga = st.sidebar.radio("Odaberite modul:", [
    "1. Trgovac (Unos)", 
    "2. Upravitelj (Potvrda)", 
    "3. Blagajna (Ispis)", 
    "4. Skladište / Izdavač", 
    "5. Arhiva & Statistika"
])

# --- MODUL 1: TRGOVAC (UNOS) ---
if uloga == "1. Trgovac (Unos)":
    st.header("📝 Unos nove reklamacije")
    with st.form("unos_form"):
        col1, col2 = st.columns(2)
        with col1:
            broj_naloga = st.text_input("Broj naloga (npr. P-26370614):")
            kupac = st.text_input("Ime i prezime / Naziv kupca (podržava č, ć, š, ž, đ):")
        with col2:
            dekor = st.text_input("Dekor / Naziv artikla:")
            komada = st.number_input("Broj reklamiranih komada:", min_value=1, value=1)
        
        nacrt_file = st.file_uploader("Priložite PDF nacrta (PanelWizard):", type=["pdf"])
        submit = st.form_submit_button("Spremi reklamaciju")

        if submit:
            if broj_naloga and kupac and nacrt_file:
                zadnjih_6 = broj_naloga.strip()[-6:]
                nacrt_bytes = nacrt_file.read()
                log_inital = dodaj_log("", f"Trgovac kreirao nalog {broj_naloga}")
                
                conn = sqlite3.connect("reklamacije.db")
                c = conn.cursor()
                c.execute('''
                    INSERT INTO reklamacije 
                    (id, broj_naloga, zadnjih_6, kupac, dekor, komada, status, vraceni_komadi, nacrt_pdf, datum_kreiranja, log_promjena)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (broj_naloga, broj_naloga, zadnjih_6, kupac, dekor, komada, 'Zaprimljeno', 'Čeka obradu', nacrt_bytes, datetime.date.today().strftime("%d.%m.%Y."), log_inital))
                conn.commit()
                conn.close()
                st.success(f"Nalog {broj_naloga} je uspješno spremljen pod pretragom: {zadnjih_6}")
            else:
                st.error("Molimo ispunite sva polja i priložite PDF nacrta.")

# --- MODUL 2: UPRAVITELJ ---
elif uloga == "2. Upravitelj (Potvrda)":
    st.header("✅ Odobrenje naloga, unos broja otpremnice i upload PDF-a")
    conn = sqlite3.connect("reklamacije.db")
    df = pd.read_sql_query("SELECT broj_naloga, kupac, dekor, komada, status FROM reklamacije WHERE status = 'Zaprimljeno'", conn)
    conn.close()

    if not df.empty:
        odabrani_nalog = st.selectbox("Odaberite nalog za odobrenje:", df['broj_naloga'].tolist())
        broj_otpremnice = st.text_input("Broj otpremnice reklamacije (npr. ORK/PU/26-00922):")
        otpremnica_file = st.file_uploader("Priložite PDF otpremnice (ORK/PU):", type=["pdf"])
        
        if st.button("Odobri nalog"):
            if otpremnica_file and broj_otpremnice:
                conn = sqlite3.connect("reklamacije.db")
                c = conn.cursor()
                c.execute("SELECT log_promjena FROM reklamacije WHERE broj_naloga = ?", (odabrani_nalog,))
                stari_log = c.fetchone()[0]
                novi_log = dodaj_log(stari_log, f"Upravitelj odobrio nalog, dodao otpremnicu {broj_otpremnice}")
                
                c.execute('''
                    UPDATE reklamacije 
                    SET status = 'Odobreno', otpremnica_pdf = ?, broj_otpremnice = ?, log_promjena = ? 
                    WHERE broj_naloga = ?
                ''', (otpremnica_file.read(), broj_otpremnice, novi_log, odabrani_nalog))
                conn.commit()
                conn.close()
                st.success(f"Nalog {odabrani_nalog} je odobren s brojem otpremnice {broj_otpremnice}!")
            else:
                st.error("Molimo upišite broj otpremnice i priložite PDF otpremnice.")
    else:
        st.info("Nema naloga koji čekaju odobrenje.")

# --- MODUL 3: BLAGAJNA ---
elif uloga == "3. Blagajna (Ispis)":
    st.header("🖨️ Blagajna - Pretraga i ispis dokumenta za kupca")
    upis_6 = st.text_input("Upišite zadnjih 6 znamenki naloga (npr. 370614):", max_chars=6)

    if upis_6:
        conn = sqlite3.connect("reklamacije.db")
        c = conn.cursor()
        c.execute("SELECT broj_naloga, kupac, dekor, komada, status, nacrt_pdf, broj_otpremnice FROM reklamacije WHERE zadnjih_6 = ?", (upis_6,))
        row = c.fetchone()
        conn.close()

        if row:
            broj_naloga, kupac, dekor, komada, status, nacrt_bytes, broj_otpremnice = row
            st.write(f"**Nalog:** {broj_naloga} | **Otpremnica:** {broj_otpremnice} | **Kupac:** {kupac} | **Dekor:** {dekor} ({komada} kom)")

            pdf_za_print = generiraj_jednostrani_pdf(nacrt_bytes, broj_naloga, kupac, dekor, komada, broj_otpremnice)
            st.download_button(
                label="📄 Preuzmi i isprintaj dokument za kupca (1 stranica)",
                data=pdf_za_print,
                file_name=f"Reklamacija_{broj_naloga}.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("Nalog s tim brojem nije pronađen.")

# --- MODUL 4: IZDAVAČ / SKLADIŠTE ---
elif uloga == "4. Skladište / Izdavač":
    st.header("📦 Skladište - Evidencija povrata reklamiranih komada")
    upis_6 = st.text_input("Pretraga po 6 znamenki naloga za izdavanje:", max_chars=6)

    if upis_6:
        conn = sqlite3.connect("reklamacije.db")
        c = conn.cursor()
        c.execute("SELECT broj_naloga, kupac, dekor, komada, status, vraceni_komadi, log_promjena, broj_otpremnice FROM reklamacije WHERE zadnjih_6 = ?", (upis_6,))
        row = c.fetchone()
        
        if row:
            broj_naloga, kupac, dekor, komada, status, vraceni_komadi, log_json, broj_otpremnice = row
            st.write(f"**Nalog:** {broj_naloga} | **Otpremnica:** {broj_otpremnice} | **Kupac:** {kupac} | **Materijal:** {dekor} ({komada} kom)")
            st.write(f"**Trenutni status povrata:** {vraceni_komadi}")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🟢 Kupac je VRATIO SVE komade"):
                    novi_log = dodaj_log(log_json, "Izdavač potvrdio: KUPAC VRATIO SVE KOMADE")
                    c.execute("UPDATE reklamacije SET status = 'Riješeno', vraceni_komadi = 'Vraćeni svi komadi', log_promjena = ? WHERE zadnjih_6 = ?", (novi_log, upis_6))
                    conn.commit()
                    st.success("Spremljeno: Kupac je vratio sve komade!")
                    posalji_email_obavijest(broj_naloga, kupac, "VRAĆENI SVI KOMADE")
            
            with col2:
                if st.button("🔴 Kupac NIJE vratio sve komade"):
                    novi_log = dodaj_log(log_json, "Izdavač potvrdio: KUPAC NIJE VRATIO SVE KOMADE")
                    c.execute("UPDATE reklamacije SET status = 'Riješeno (Nedostaje materijal)', vraceni_komadi = 'NISU vraćeni svi komadi', log_promjena = ? WHERE zadnjih_6 = ?", (novi_log, upis_6))
                    conn.commit()
                    st.error("Spremljeno: Kupac NIJE vratio sve komade!")
                    posalji_email_obavijest(broj_naloga, kupac, "NISU VRAĆENI SVI KOMADI")
        else:
            st.warning("Nalog nije pronađen.")
        conn.close()

# --- MODUL 5: ARHIVA & STATISTIKA ---
elif uloga == "5. Arhiva & Statistika":
    st.header("📊 Arhiva i Statistika Povrata")
    conn = sqlite3.connect("reklamacije.db")
    df = pd.read_sql_query("SELECT broj_naloga, broj_otpremnice, kupac, dekor, komada, status, vraceni_komadi, datum_kreiranja, log_promjena FROM reklamacije", conn)
    conn.close()

    if not df.empty:
        st.subheader("📋 Arhiva svih naloga")
        st.dataframe(df[['broj_naloga', 'broj_otpremnice', 'kupac', 'dekor', 'komada', 'status', 'vraceni_komadi', 'datum_kreiranja']], use_container_width=True)

        st.subheader("📈 Statistika povrata")
        stat_df = df['vraceni_komadi'].value_counts().reset_index()
        stat_df.columns = ['Status povrata', 'Broj naloga']
        st.bar_chart(stat_df.set_index('Status povrata'))

        st.subheader("📜 Pregled Loga promjena")
        odabrani_nalog = st.selectbox("Odaberite nalog za pregled povijesti:", df['broj_naloga'].tolist())
        log_data = df[df['broj_naloga'] == odabrani_nalog]['log_promjena'].values[0]
        if log_data:
            logovi = json.loads(log_data)
            for l in logovi:
                st.text(l)
    else:
        st.info("Nema zapisa u arhivi.")
