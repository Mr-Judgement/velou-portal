#!/usr/bin/env python3
"""
Generate 4 Airtable-ready CSV files from VeloU sample data.
Output files:
  1. airtable_athletes.csv           — one row per athlete, all current metrics
  2. airtable_energy_score_history.csv
  3. airtable_velocity_history.csv   — aggregated per session from TrackMan
  4. airtable_eval_history.csv
"""

import csv
import io
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "Sample Data")
OUT_DIR = os.path.dirname(__file__)


def read_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def read_csv_cols(filename, cols):
    """Read only specific columns (by index) to avoid multiline-JSON corruption."""
    path = os.path.join(DATA_DIR, filename)
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        raw_reader = csv.reader(f)
        headers = next(raw_reader)
        idx = {col: headers.index(col) for col in cols if col in headers}
        for raw in raw_reader:
            if len(raw) < max(idx.values()) + 1:
                continue
            row = {col: raw[i].strip() for col, i in idx.items()}
            rows.append(row)
    return rows


def clean(val):
    if val is None:
        return ""
    v = str(val).strip()
    return "" if v == "NULL" else v


def latest_by_date(rows, date_field, athlete_field="athlete_id"):
    """Return dict of athlete_id -> most-recent row."""
    by_athlete = defaultdict(list)
    for row in rows:
        by_athlete[row[athlete_field]].append(row)
    result = {}
    for aid, recs in by_athlete.items():
        recs.sort(key=lambda r: r.get(date_field, ""), reverse=True)
        result[aid] = recs[0]
    return result


def best_trial_per_session(rows, date_field, metric_field, athlete_field="athlete_id", higher_is_better=True):
    """Aggregate trials: return best value per athlete per date, then latest date."""
    sessions = defaultdict(lambda: defaultdict(list))
    for row in rows:
        val_str = row.get(metric_field, "").strip()
        if val_str and val_str != "NULL":
            try:
                sessions[row[athlete_field]][row[date_field]].append(float(val_str))
            except ValueError:
                pass

    result = {}
    for aid, dates in sessions.items():
        latest_date = sorted(dates.keys(), reverse=True)[0]
        vals = dates[latest_date]
        best = max(vals) if higher_is_better else min(vals)
        result[aid] = {"date": latest_date, "best": best, "avg": sum(vals) / len(vals), "count": len(vals)}
    return result


def round2(val):
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# 1. airtable_athletes.csv
# ---------------------------------------------------------------------------

def build_athletes():
    athletes = read_csv("athletes sample data.csv")
    energy_all = read_csv("athlete_energy_scores_all sample data.csv")
    armcare = read_csv("armcare_exams sample data.csv")
    whoop_recovery = read_csv("whoop2 sample data.csv")
    whoop_sleep = read_csv("whoop sleep sample data.csv")
    evals = read_csv("athlete evals sample data.csv")

    # CMJ — read only safe columns (before raw_json at index 20)
    cmj_cols = ["athlete_id", "test_date", "trial_number", "jump_height_cm",
                 "peak_power_w", "peak_power_bw", "peak_force_n", "peak_force_bw",
                 "rsi_modified", "contraction_time_ms", "flight_time_ms",
                 "peak_force_asym_pct", "eccentric_peak_force_n", "eccentric_duration_ms",
                 "concentric_peak_power_w"]
    cmj_rows = read_csv_cols("vald_cmj sample data.csv", cmj_cols)

    imtp_cols = ["athlete_id", "test_date", "trial_number", "peak_force_n",
                 "peak_force_bw", "peak_force_left_n", "peak_force_right_n",
                 "force_asym_pct", "rfd_0_50ms", "rfd_0_100ms", "impulse_net"]
    imtp_rows = read_csv_cols("vald_imtp sample data.csv", imtp_cols)

    # Aggregated lookups
    energy_latest = latest_by_date(
        [r for r in energy_all if clean(r.get("total_energy_score"))],
        "cmj_date"
    )
    # For athletes with no total_energy_score, still get their identity row
    energy_by_athlete = {}
    for r in energy_all:
        aid = r["athlete_id"]
        if aid not in energy_by_athlete:
            energy_by_athlete[aid] = r
        elif r.get("cmj_date", "") > energy_by_athlete[aid].get("cmj_date", ""):
            energy_by_athlete[aid] = r

    armcare_latest = latest_by_date(armcare, "exam_date")
    recovery_latest = latest_by_date(
        [r for r in whoop_recovery if clean(r.get("score_state")) == "SCORED"],
        "date"
    )
    sleep_latest = latest_by_date(
        [r for r in whoop_sleep if r.get("is_nap", "1") == "0" and clean(r.get("score_state")) == "SCORED"],
        "date"
    )

    # Latest eval per athlete
    eval_latest = latest_by_date(evals, "test_date")

    # CMJ: best jump_height per athlete's latest session
    cmj_best = best_trial_per_session(cmj_rows, "test_date", "jump_height_cm")
    imtp_best = best_trial_per_session(imtp_rows, "test_date", "peak_force_bw")
    # Absolute-unit force/power (same best trial in practice, since bodyweight
    # is constant within a session and cancels out of the bw-relative ranking).
    cmj_power_best = best_trial_per_session(cmj_rows, "test_date", "peak_power_w")
    imtp_force_best = best_trial_per_session(imtp_rows, "test_date", "peak_force_n")

    fields = [
        "athlete_id", "name", "position", "throws", "age", "height_inches", "weight_lbs",
        "playing_level", "current_level", "current_team", "photo_url",
        # Energy scores (current)
        "total_energy_score", "energy_potential_score", "energy_production_score",
        "energy_transference_score", "energy_interference_score", "energy_delta",
        "energy_score_date",
        # Physical testing
        "top_fastball_velo", "arm_score", "irt_strength", "ert_strength",
        "irt_rom", "ert_rom",
        "scaption_strength", "grip_strength",
        "armcare_date",
        # CMJ
        "cmj_date", "jump_height_cm_best", "peak_power_w_kg", "cmj_peak_power_w",
        "cmj_rsi_modified", "peak_force_asym_pct",
        # IMTP
        "imtp_date", "imtp_peak_force_bw", "imtp_peak_force_n",
        # WHOOP Recovery (latest)
        "whoop_recovery_date", "recovery_score", "hrv_rmssd_milli", "resting_hr",
        "spo2_pct",
        # WHOOP Sleep (latest)
        "whoop_sleep_date", "sleep_performance_pct", "sleep_efficiency_pct",
        "slow_wave_milli", "rem_sleep_milli", "respiratory_rate",
    ]

    rows_out = []
    for ath in athletes:
        aid = ath["athlete_id"]
        if clean(ath.get("is_active", "0")) != "1":
            continue  # skip inactive

        e = energy_by_athlete.get(aid, {})
        ac = armcare_latest.get(aid, {})
        rec = recovery_latest.get(aid, {})
        slp = sleep_latest.get(aid, {})
        ev = eval_latest.get(aid, {})
        cmj = cmj_best.get(aid, {})
        imtp = imtp_best.get(aid, {})
        cmj_pw = cmj_power_best.get(aid, {})
        imtp_fn = imtp_force_best.get(aid, {})

        # Height: prefer energy_scores > athletes table
        height_in = clean(e.get("height_inches")) or clean(ath.get("height_in"))
        weight = clean(e.get("weight_lbs")) or clean(ath.get("weight_lbs"))

        row = {
            "athlete_id": aid,
            "name": clean(ath.get("name")),
            "position": clean(ath.get("position")) or clean(ev.get("position")),
            "throws": clean(ath.get("throws")),
            "age": clean(ath.get("age")) or clean(ev.get("age")),
            "height_inches": height_in,
            "weight_lbs": round2(weight) if weight else "",
            "playing_level": clean(ath.get("playing_level")) or clean(ev.get("current_level")),
            "current_level": clean(ev.get("current_level")),
            "current_team": clean(ev.get("current_team")),
            "photo_url": clean(ath.get("photo_url")),
            # Energy scores
            "total_energy_score": round2(e.get("total_energy_score")),
            "energy_potential_score": round2(e.get("energy_potential_score")),
            "energy_production_score": round2(e.get("energy_production_score")),
            "energy_transference_score": round2(e.get("energy_transference_score")),
            "energy_interference_score": round2(e.get("energy_interference_score")),
            "energy_delta": round2(e.get("energy_delta")),
            "energy_score_date": clean(e.get("cmj_date")),
            # Performance
            "top_fastball_velo": round2(e.get("top_fastball_velo")),
            "arm_score": round2(ac.get("arm_score") or e.get("arm_score")),
            "irt_strength": round2(ac.get("irt_strength") or e.get("irt_strength")),
            "ert_strength": round2(ac.get("ert_strength") or e.get("ert_strength")),
            "irt_rom": clean(ac.get("irt_rom")),
            "ert_rom": clean(ac.get("ert_rom")),
            "scaption_strength": round2(e.get("scaption_strength")),
            "grip_strength": round2(e.get("grip_strength")),
            "armcare_date": clean(ac.get("exam_date") or e.get("armcare_date")),
            # CMJ
            "cmj_date": cmj.get("date", clean(e.get("cmj_date"))),
            "jump_height_cm_best": round2(cmj.get("best")),
            "peak_power_w_kg": round2(e.get("peak_power_w_kg")),
            "cmj_peak_power_w": round2(cmj_pw.get("best")),
            "cmj_rsi_modified": "",  # populated below
            "peak_force_asym_pct": "",
            # IMTP
            "imtp_date": imtp.get("date", clean(e.get("imtp_date"))),
            "imtp_peak_force_bw": round2(imtp.get("best") or e.get("peak_force_n_kg")),
            "imtp_peak_force_n": round2(imtp_fn.get("best")),
            # WHOOP Recovery
            "whoop_recovery_date": clean(rec.get("date")),
            "recovery_score": clean(rec.get("recovery_score")),
            "hrv_rmssd_milli": round2(rec.get("hrv_rmssd_milli")),
            "resting_hr": clean(rec.get("resting_hr")),
            "spo2_pct": round2(rec.get("spo2_pct")),
            # WHOOP Sleep
            "whoop_sleep_date": clean(slp.get("date")),
            "sleep_performance_pct": clean(slp.get("sleep_performance_pct")),
            "sleep_efficiency_pct": round2(slp.get("sleep_efficiency_pct")),
            "slow_wave_milli": clean(slp.get("slow_wave_milli")),
            "rem_sleep_milli": clean(slp.get("rem_sleep_milli")),
            "respiratory_rate": round2(slp.get("respiratory_rate")),
        }

        # Fill RSI from CMJ raw data (best trial on latest date)
        cmj_rsi_data = best_trial_per_session(cmj_rows, "test_date", "rsi_modified")
        row["cmj_rsi_modified"] = round2(cmj_rsi_data.get(aid, {}).get("best"))

        # Peak force asym from CMJ
        cmj_asym_data = best_trial_per_session(
            [r for r in cmj_rows if clean(r.get("peak_force_asym_pct"))],
            "test_date", "peak_force_asym_pct", higher_is_better=False
        )
        row["peak_force_asym_pct"] = round2(cmj_asym_data.get(aid, {}).get("best"))

        rows_out.append(row)

    out_path = os.path.join(OUT_DIR, "airtable_athletes.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"✓  airtable_athletes.csv  ({len(rows_out)} rows)")


# ---------------------------------------------------------------------------
# 2. airtable_energy_score_history.csv
# ---------------------------------------------------------------------------

def build_energy_history():
    rows = read_csv("athlete_energy_scores_history sample data.csv")

    fields = [
        "athlete_id", "name", "score_date",
        "total_energy_score", "energy_potential_score", "energy_production_score",
        "energy_transference_score", "energy_interference_score", "energy_delta",
        "top_fastball_velo", "arm_score",
        "peak_power_w_kg", "peak_force_n_kg", "concentric_impulse_ns",
        "throw_1lb_mph", "throw_2lb_mph", "kneeling_throw_mph",
        "irt_strength", "ert_strength", "scaption_strength", "grip_strength",
    ]

    rows_out = []
    for row in rows:
        rows_out.append({
            "athlete_id": clean(row.get("athlete_id")),
            "name": clean(row.get("name")),
            "score_date": clean(row.get("score_date")),
            "total_energy_score": round2(row.get("total_energy_score")),
            "energy_potential_score": round2(row.get("energy_potential_score")),
            "energy_production_score": round2(row.get("energy_production_score")),
            "energy_transference_score": round2(row.get("energy_transference_score")),
            "energy_interference_score": round2(row.get("energy_interference_score")),
            "energy_delta": round2(row.get("energy_delta")),
            "top_fastball_velo": round2(row.get("top_fastball_velo")),
            "arm_score": round2(row.get("arm_score")),
            "peak_power_w_kg": round2(row.get("peak_power_w_kg")),
            "peak_force_n_kg": round2(row.get("peak_force_n_kg")),
            "concentric_impulse_ns": round2(row.get("concentric_impulse_ns")),
            "throw_1lb_mph": round2(row.get("throw_1lb_mph")),
            "throw_2lb_mph": round2(row.get("throw_2lb_mph")),
            "kneeling_throw_mph": round2(row.get("kneeling_throw_mph")),
            "irt_strength": round2(row.get("irt_strength")),
            "ert_strength": round2(row.get("ert_strength")),
            "scaption_strength": round2(row.get("scaption_strength")),
            "grip_strength": round2(row.get("grip_strength")),
        })

    # Sort by athlete_id, then date descending
    rows_out.sort(key=lambda r: (r["athlete_id"], r["score_date"]), reverse=False)

    out_path = os.path.join(OUT_DIR, "airtable_energy_score_history.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"✓  airtable_energy_score_history.csv  ({len(rows_out)} rows)")


# ---------------------------------------------------------------------------
# 3. airtable_velocity_history.csv  (TrackMan aggregated per session)
# ---------------------------------------------------------------------------

def build_velocity_history():
    pitch_cols = ["athlete_id", "pitch_date", "tagged_pitch_type", "rel_speed",
                  "spin_rate", "induced_vert_break", "horz_break", "extension",
                  "rel_height", "rel_side"]
    rows = read_csv_cols("trackman_piches sample data.csv", pitch_cols)

    # Names lookup
    athletes = read_csv("athletes sample data.csv")
    name_map = {r["athlete_id"]: clean(r["name"]) for r in athletes}

    # Group by athlete + date
    sessions = defaultdict(lambda: defaultdict(lambda: {
        "all_speeds": [],
        "fb_speeds": [],
        "fb_spins": [],
        "fb_ivbs": [],
        "fb_hbs": [],
    }))

    for row in rows:
        aid = row["athlete_id"]
        date = row["pitch_date"]
        speed_str = clean(row.get("rel_speed"))
        pitch_type = clean(row.get("tagged_pitch_type"))

        if speed_str:
            try:
                speed = float(speed_str)
                sessions[aid][date]["all_speeds"].append(speed)
                if pitch_type == "Fastball":
                    sessions[aid][date]["fb_speeds"].append(speed)
                    spin_str = clean(row.get("spin_rate"))
                    if spin_str:
                        sessions[aid][date]["fb_spins"].append(float(spin_str))
                    ivb_str = clean(row.get("induced_vert_break"))
                    if ivb_str:
                        sessions[aid][date]["fb_ivbs"].append(float(ivb_str))
                    hb_str = clean(row.get("horz_break"))
                    if hb_str:
                        sessions[aid][date]["fb_hbs"].append(float(hb_str))
            except ValueError:
                pass

    fields = [
        "athlete_id", "name", "pitch_date",
        "max_fastball_velo", "avg_fastball_velo", "fastball_count",
        "avg_fb_spin_rate", "avg_fb_induced_vbreak", "avg_fb_hbreak",
        "total_pitch_count",
    ]

    rows_out = []
    for aid in sorted(sessions.keys()):
        for date in sorted(sessions[aid].keys()):
            s = sessions[aid][date]
            fb = s["fb_speeds"]
            all_p = s["all_speeds"]
            spins = s["fb_spins"]
            ivbs = s["fb_ivbs"]
            hbs = s["fb_hbs"]

            rows_out.append({
                "athlete_id": aid,
                "name": name_map.get(aid, ""),
                "pitch_date": date,
                "max_fastball_velo": round2(max(fb)) if fb else "",
                "avg_fastball_velo": round2(sum(fb) / len(fb)) if fb else "",
                "fastball_count": len(fb),
                "avg_fb_spin_rate": round2(sum(spins) / len(spins)) if spins else "",
                "avg_fb_induced_vbreak": round2(sum(ivbs) / len(ivbs)) if ivbs else "",
                "avg_fb_hbreak": round2(sum(hbs) / len(hbs)) if hbs else "",
                "total_pitch_count": len(all_p),
            })

    out_path = os.path.join(OUT_DIR, "airtable_velocity_history.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"✓  airtable_velocity_history.csv  ({len(rows_out)} rows / {len(sessions)} athletes)")


# ---------------------------------------------------------------------------
# 4. airtable_eval_history.csv
# ---------------------------------------------------------------------------

def build_eval_history():
    rows = read_csv("athlete evals sample data.csv")

    fields = [
        "athlete_id", "name", "test_date", "age", "group_name",
        "current_level", "current_team", "position", "height_inches",
        "ankle_dorsiflexion", "right_hip_rom", "left_hip_rom", "hip_extension",
        "thoracic_extension", "shoulder_flexion", "shoulder_arc", "cervical_rotation",
        "throw_1lb_mph", "throw_2lb_mph", "kneeling_throw_mph",
    ]

    # De-duplicate: keep only the latest eval per athlete per date
    seen = set()
    rows_out = []
    for row in sorted(rows, key=lambda r: (r["athlete_id"], r["test_date"])):
        key = (row["athlete_id"], row["test_date"])
        if key in seen:
            continue
        seen.add(key)
        rows_out.append({
            "athlete_id": clean(row.get("athlete_id")),
            "name": "",  # will fill from athletes
            "test_date": clean(row.get("test_date")),
            "age": clean(row.get("age")),
            "group_name": clean(row.get("group_name")),
            "current_level": clean(row.get("current_level")),
            "current_team": clean(row.get("current_team")),
            "position": clean(row.get("position")),
            "height_inches": clean(row.get("height_inches")),
            "ankle_dorsiflexion": clean(row.get("ankle_dorsiflexion")),
            "right_hip_rom": clean(row.get("right_hip_rom")),
            "left_hip_rom": clean(row.get("left_hip_rom")),
            "hip_extension": clean(row.get("hip_extension")),
            "thoracic_extension": clean(row.get("thoracic_extension")),
            "shoulder_flexion": clean(row.get("shoulder_flexion")),
            "shoulder_arc": clean(row.get("shoulder_arc")),
            "cervical_rotation": clean(row.get("cervical_rotation")),
            "throw_1lb_mph": round2(row.get("throw_1lb_mph")),
            "throw_2lb_mph": round2(row.get("throw_2lb_mph")),
            "kneeling_throw_mph": round2(row.get("kneeling_throw_mph")),
        })

    # Fill names
    athletes = read_csv("athletes sample data.csv")
    name_map = {r["athlete_id"]: clean(r["name"]) for r in athletes}
    for row in rows_out:
        row["name"] = name_map.get(row["athlete_id"], "")

    out_path = os.path.join(OUT_DIR, "airtable_eval_history.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"✓  airtable_eval_history.csv  ({len(rows_out)} rows)")


if __name__ == "__main__":
    build_athletes()
    build_energy_history()
    build_velocity_history()
    build_eval_history()
    print("\nAll 4 Airtable CSVs written to:", OUT_DIR)
