with m3:
            st.markdown('<div class="metric-glass-card">', unsafe_allow_html=True)
            st.metric("Net Balance", f"Rp {fmt_idr(bal)}")
            st.markdown('</div>', unsafe_allow_html=True)

        st.write("")
        col_ov1, col_ov2 = st.columns(2)
        with col_ov1:
            st.markdown(f"""
                <div class="workspace-card">
                    <h4 style="color:#ffffff; margin-top:0; font-weight:800;">📌 Quick Actions</h4>
                    <p style="font-size:12px; color:#e2d8f3;">Akses cepat untuk mencatat transaksi atau agenda harian.</p>
                </div>
            """, unsafe_allow_html=True)
        with col_ov2:
            st.markdown(f"""
                <div class="workspace-card">
                    <h4 style="color:#ffffff; margin-top:0; font-weight:800;">⚡ System Status</h4>
                    <p style="font-size:12px; color:#e2d8f3;">Telegram Bot & Database SQLite aktif berjalan normal.</p>
                </div>
            """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # MODULE: FINANCIAL
    # ---------------------------------------------------------
    elif nav == "FINANCIAL":
        st.markdown("<h3 style='color:#ffffff; font-weight:800; margin-bottom:16px;'>Financial Management</h3>", unsafe_allow_html=True)
        
        with st.form("form_trans"):
            st.markdown("#### Tambah Transaksi Baru")
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                t_type = st.selectbox("Tipe", ["Expense", "Income"])
                t_cat = st.selectbox("Kategori", ["Makan/Minum", "Transport", "Belanja", "Utilitas", "Gaji", "Lainnya"])
                t_date = st.date_input("Tanggal", datetime.date.today())
            with f_col2:
                t_amount_raw = st.text_input("Nominal (contoh: 50k, 1.5jt, atau 50000)")
                t_pay = st.selectbox("Metode Pembayaran", ["Cash", "Transfer Bank", "QRIS", "E-Wallet"])
                t_desc = st.text_input("Keterangan")
            
            if st.form_submit_button("SIMPAN TRANSAKSI"):
                amount_parsed = parse_amount(t_amount_raw)
                if amount_parsed <= 0:
                    st.warning("Mohon masukkan nominal yang valid.")
                else:
                    conn.execute(
                        "INSERT INTO transactions (user, date, type, category, description, amount, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user, str(t_date), t_type, t_cat, t_desc, amount_parsed, t_pay)
                    )
                    conn.commit()
                    st.success("Transaksi berhasil disimpan!")
                    st.rerun()

        st.write("")
        st.markdown("#### Riwayat Transaksi")
        df_tx = pd.read_sql_query("SELECT id, date, type, category, description, amount, payment_method FROM transactions WHERE user=? ORDER BY date DESC", conn, params=(user,))
        if not df_tx.empty:
            st.dataframe(df_tx, use_container_width=True)
        else:
            st.info("Belum ada data transaksi tercatat.")

    # ---------------------------------------------------------
    # MODULE: CALENDAR & WORK EVENTS
    # ---------------------------------------------------------
    elif nav == "CALENDAR":
        st.markdown("<h3 style='color:#ffffff; font-weight:800; margin-bottom:16px;'>Calendar & Schedule</h3>", unsafe_allow_html=True)
        
        # Navigasi Bulan Kalender
        c_yr, c_mo, c_btn = st.columns([1, 1, 2])
        with c_yr:
            yr = st.number_input("Tahun", value=st.session_state['cal_year'], min_value=2020, max_value=2030, step=1)
            st.session_state['cal_year'] = int(yr)
        with c_mo:
            mo = st.number_input("Bulan", value=st.session_state['cal_month'], min_value=1, max_value=12, step=1)
            st.session_state['cal_month'] = int(mo)

        year = st.session_state['cal_year']
        month = st.session_state['cal_month']

        # Ambil data event dari database
        ev_rows = conn.execute(
            "SELECT id, date, start_time, title, reminder_location, reminder_channel FROM work_events WHERE user=? AND date LIKE ?",
            (user, f"{year}-{month:02d}%")
        ).fetchall()
        
        event_map = {}
        for ev_id, ev_date, ev_time, ev_title, ev_loc, ev_chan in ev_rows:
            event_map.setdefault(ev_date, []).append({
                "id": ev_id, "time": ev_time, "title": ev_title, "channel": ev_chan
            })

        # Render Grid Kalender 7 Kolom
        days_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        head_cols = st.columns(7)
        for i, d_name in enumerate(days_names):
            with head_cols[i]:
                st.markdown(f'<div class="cal-header-box">{d_name}</div>', unsafe_allow_html=True)

        cal_matrix = pycal.monthcalendar(year, month)
        for week in cal_matrix:
            cols = st.columns(7)
            for i, day_num in enumerate(week):
                with cols[i]:
                    if day_num == 0:
                        st.markdown('<div class="cal-grid-day" style="opacity:0.2;"></div>', unsafe_allow_html=True)
                    else:
                        d_str = f"{year}-{month:02d}-{day_num:02d}"
                        is_today = (d_str == str(datetime.date.today()))
                        
                        day_inner = f'<div class="cal-grid-day">'
                        if is_today:
                            day_inner += f'<span class="cal-today-circle">{day_num}</span>'
                        else:
                            day_inner += f'<span style="font-size:11px; font-weight:700; color:#e2d8f3;">{day_num}</span>'

                        if d_str in event_map:
                            for ev in event_map[d_str]:
                                badge_cls = "event-badge-sent" if ev["channel"] == "Sent" else "event-badge-pending"
                                day_inner += f'<span class="{badge_cls}" title="{ev["title"]}">• {ev["time"]} {ev["title"]}</span>'
                        
                        day_inner += '</div>'
                        st.markdown(day_inner, unsafe_allow_html=True)

        st.write("")
        with st.form("form_event"):
            st.markdown("#### Tambah Agenda / Event Baru")
            e_col1, e_col2 = st.columns(2)
            with e_col1:
                e_title = st.text_input("Judul Agenda / Event")
                e_date = st.date_input("Tanggal Event", datetime.date.today())
                e_time = st.text_input("Jam (HH:MM)", value="10:00")
            with e_col2:
                e_type = st.selectbox("Tipe Agenda", ["Meeting", "Deadline", "Reminder", "Personal"])
                e_prio = st.selectbox("Prioritas", ["High", "Medium", "Low"])
                e_target = st.selectbox("Penerima Telegram", list(TELEGRAM_TARGETS.keys()))

            if st.form_submit_button("SIMPAN & AKTIFKAN PENGINGAT"):
                norm_t = normalize_time(e_time)
                if not norm_t:
                    st.warning("Format jam tidak valid. Gunakan format HH:MM (contoh: 10:00).")
                elif not e_title:
                    st.warning("Mohon isi judul agenda.")
                else:
                    chat_id_val = TELEGRAM_TARGETS.get(e_target, "8696187764")
                    conn.execute(
                        "INSERT INTO work_events (user, date, start_time, end_time, title, type, location, priority, reminder_channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (user, str(e_date), norm_t, norm_t, e_title, e_type, chat_id_val, e_prio, "Telegram Bot")
                    )
                    conn.commit()
                    st.success("Agenda berhasil disimpan dan pengingat Telegram diaktifkan!")
                    st.rerun()

    # ---------------------------------------------------------
    # MODULE: TO-DO LIST
    # ---------------------------------------------------------
    elif nav == "TO-DO LIST":
        st.markdown("<h3 style='color:#ffffff; font-weight:800; margin-bottom:16px;'>To-Do List / Kanban</h3>", unsafe_allow_html=True)
        
        with st.form("form_todo"):
            t_name = st.text_input("Nama Tugas Baru")
            t_prio = st.selectbox("Prioritas", ["High", "Medium", "Low"])
            if st.form_submit_button("TAMBAH TUGAS"):
                if t_name:
                    conn.execute(
                        "INSERT INTO todo_list (user, task_name, priority, is_done, created_date) VALUES (?, ?, ?, 0, ?)",
                        (user, t_name, t_prio, str(datetime.date.today()))
                    )
                    conn.commit()
                    st.success("Tugas berhasil ditambahkan!")
                    st.rerun()
                else:
                    st.warning("Nama tugas tidak boleh kosong.")

        st.write("")
        td_rows = conn.execute("SELECT id, task_name, priority, is_done FROM todo_list WHERE user=?", (user,)).fetchall()
        
        col_td1, col_td2 = st.columns(2)
        with col_td1:
            st.markdown("#### 📌 Pending Tasks")
            for tid, tname, tprio, isdone in td_rows:
                if isdone == 0:
                    prio_cls = f"prio-tag-{tprio.lower()}" if tprio in ["High", "Medium", "Low"] else "prio-tag-low"
                    st.markdown(f"""
                        <div class="kanban-card">
                            <span class="{prio_cls}">{tprio}</span>
                            <div style="font-weight:700; color:#ffffff; margin-top:6px;">{tname}</div>
                        </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"Selesai #{tid}", key=f"done_{tid}"):
                        conn.execute("UPDATE todo_list SET is_done=1 WHERE id=?", (tid,))
                        conn.commit()
                        st.rerun()

        with col_td2:
            st.markdown("#### ✅ Completed Tasks")
            for tid, tname, tprio, isdone in td_rows:
                if isdone == 1:
                    st.markdown(f"""
                        <div class="kanban-card-finish">
                            <div style="font-weight:700; color:#10b981; text-decoration: line-through;">{tname}</div>
                        </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"Batal #{tid}", key=f"undone_{tid}"):
                        conn.execute("UPDATE todo_list SET is_done=0 WHERE id=?", (tid,))
                        conn.commit()
                        st.rerun()

    # ---------------------------------------------------------
    # MODULE: GOALS & HABIT
    # ---------------------------------------------------------
    elif nav == "GOALS & HABIT":
        st.markdown("<h3 style='color:#ffffff; font-weight:800; margin-bottom:16px;'>Financial Goals & Habits</h3>", unsafe_allow_html=True)
        
        with st.form("form_goal"):
            st.markdown("#### Tambah Financial Goal")
            g_name = st.text_input("Nama Target (contoh: Dana Darurat)")
            g_target = st.text_input("Target Nominal (contoh: 10jt)")
            g_current = st.text_input("Terkumpul Saat Ini (contoh: 2jt)")
            g_date = st.date_input("Target Tanggal", datetime.date.today())
            
            if st.form_submit_button("SIMPAN GOAL"):
                t_amt = parse_amount(g_target)
                c_amt = parse_amount(g_current)
                if g_name and t_amt > 0:
                    conn.execute(
                        "INSERT INTO fin_goals (user, target_name, target_amount, current_amount, target_date) VALUES (?, ?, ?, ?, ?)",
                        (user, g_name, t_amt, c_amt, str(g_date))
                    )
                    conn.commit()
                    st.success("Financial Goal berhasil disimpan!")
                    st.rerun()
                else:
                    st.warning("Mohon lengkapi data dengan benar.")

        st.write("")
        goals = conn.execute("SELECT target_name, target_amount, current_amount, target_date FROM fin_goals WHERE user=?", (user,)).fetchall()
        for g_name, t_amt, c_amt, t_date in goals:
            pct = min(100.0, (c_amt / t_amt * 100)) if t_amt > 0 else 0.0
            st.markdown(f"""
                <div class="workspace-card">
                    <div style="font-weight:800; color:#ffffff; font-size:15px; margin-bottom:4px;">🎯 {g_name}</div>
                    <div style="font-size:12px; color:#e2d8f3; margin-bottom:8px;">Terkumpul: Rp {fmt_idr(c_amt)} dari Rp {fmt_idr(t_amt)} ({pct:.1f}%) — Target: {t_date}</div>
                </div>
            """, unsafe_allow_html=True)
            st.progress(int(pct))

    # ---------------------------------------------------------
    # MODULE: NOTES
    # ---------------------------------------------------------
    elif nav == "NOTES":
        st.markdown("<h3 style='color:#ffffff; font-weight:800; margin-bottom:16px;'>Post-it Notes & Quick Logs</h3>", unsafe_allow_html=True)
        
        with st.form("form_note"):
            n_title = st.text_input("Judul Catatan")
            n_content = st.text_area("Isi Catatan")
            if st.form_submit_button("SIMPAN CATATAN"):
                if n_title and n_content:
                    conn.execute(
                        "INSERT INTO notes_log (user, title, content, created_at) VALUES (?, ?, ?, ?)",
                        (user, n_title, n_content, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
                    )
                    conn.commit()
                    st.success("Catatan berhasil disimpan!")
                    st.rerun()
                else:
                    st.warning("Judul dan isi catatan tidak boleh kosong.")

        st.write("")
        notes = conn.execute("SELECT id, title, content, created_at FROM notes_log WHERE user=? ORDER BY id DESC", (user,)).fetchall()
        for nid, ntitle, ncont, ntime in notes:
            st.markdown(f"""
                <div class="postit-card">
                    <div class="postit-title">{ntitle}</div>
                    <div class="postit-content">{ncont}</div>
                    <div class="postit-date">{ntime}</div>
                </div>
            """, unsafe_allow_html=True)

    conn.close()
