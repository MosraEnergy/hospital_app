"""Visit-based reporting; each encounter counts once per diagnosis."""
import pandas as pd

ADMISSIONS = ["Short-Day", "Short-Day Admission", "Standard Admission"]


def visit_frame(records):
    frame = pd.DataFrame(records)
    if not frame.empty:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("Africa/Lagos")
    return frame


def filter_visits(frame, start, end):
    return frame.loc[frame["timestamp"].dt.date.between(start, end)].copy()


def diagnosis_counts(frame):
    exploded = frame[["id", "diagnoses"]].explode("diagnoses").dropna()
    exploded["key"] = exploded["diagnoses"].str.strip().str.casefold()
    exploded = exploded[exploded["key"] != ""].drop_duplicates(["id", "key"])
    labels = exploded.groupby("key")["diagnoses"].first()
    counts = exploded.groupby("key").size().sort_values(ascending=False)
    return pd.DataFrame({"Diagnosis": labels.reindex(counts.index).values,
                         "Visits": counts.values})


def daily_counts(frame, start, end):
    counts = frame.groupby(frame["timestamp"].dt.date).size()
    days = pd.date_range(start, end, freq="D").date
    return pd.DataFrame({"Date": days, "Visits": counts.reindex(days, fill_value=0).values})


def outcomes(frame):
    admission = frame["admission"].fillna("No Entry").replace({"Short-Day": "Short-Day Admission"})
    result = admission.value_counts().rename_axis("Outcome").reset_index(name="Visits")
    result["Outcome"] = result["Outcome"].replace({"No Entry": "Outpatient / no admission"})
    return result
