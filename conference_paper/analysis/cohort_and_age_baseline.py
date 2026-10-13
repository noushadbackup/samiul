"""Cohort demographics and an age-only (and age+sex) baseline on the exact CV folds used
for the deep models. Needs no MRI and no GPU: it uses only labels.csv and splits/*.json
from the code repository (github.com/SamuelCormaken/Deep-Learning-for-Alzheimers-MRI).

Only aggregate statistics are written (cohort_age_baseline.json); no subject-level ADNI
data are copied into this repository.

Run:  python3 cohort_and_age_baseline.py /path/to/Deep-Learning-for-Alzheimers-MRI
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, f1_score, roc_auc_score, accuracy_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

TASKS = {"binary": (["CN", "AD"], "cv5_binary.json"), "3class": (["CN", "MCI", "AD"], "cv5_3class.json")}


def subject_table(labels):
    df = pd.read_csv(labels)
    g = df.groupby("subject_id")
    subj = pd.DataFrame({
        "group": g["group"].agg(lambda s: s.iloc[0]),
        "n_groups": g["group"].nunique(),
        "sex": g["sex"].agg(lambda s: s.iloc[0]),
        "age_first": g["age"].min(),
        "age_last": g["age"].max(),
        "n_scans": g.size(),
    })
    subj["age_mean"] = g["age"].mean()
    subj["span_years"] = subj["age_last"] - subj["age_first"]
    return df, subj


def demographics(df, subj):
    out = {"n_scans": int(len(df)), "n_subjects": int(len(subj)),
           "subjects_with_inconsistent_group": int((subj["n_groups"] > 1).sum()),
           "scans_per_subject_mean": float(subj["n_scans"].mean()),
           "scans_per_subject_counts": {int(k): int(v) for k, v in subj["n_scans"].value_counts().sort_index().items()},
           "age_span_years_median": float(subj["span_years"].median()),
           "age_span_years_max": float(subj["span_years"].max()),
           "groups": {}}
    for grp in ["CN", "MCI", "AD"]:
        s = subj[subj["group"] == grp]
        out["groups"][grp] = {
            "subjects": int(len(s)), "scans": int(s["n_scans"].sum()),
            "age_first_mean": float(s["age_first"].mean()), "age_first_sd": float(s["age_first"].std()),
            "female_pct": float((s["sex"] == "F").mean() * 100),
        }
    cn, ad = subj[subj.group == "CN"]["age_first"], subj[subj.group == "AD"]["age_first"]
    t = stats.ttest_ind(cn, ad, equal_var=False)
    out["age_CN_vs_AD_welch"] = {"t": float(t.statistic), "p": float(t.pvalue),
                                 "mean_diff_AD_minus_CN": float(ad.mean() - cn.mean())}
    tab = pd.crosstab(subj["group"], subj["sex"])
    chi = stats.chi2_contingency(tab.values)
    out["sex_by_group_chi2"] = {"chi2": float(chi[0]), "p": float(chi[1])}
    return out


def baseline(subj, splits_dir, task, features):
    groups, fname = TASKS[task]
    split = json.load(open(os.path.join(splits_dir, fname)))
    lab = {g: i for i, g in enumerate(groups)}
    s = subj[subj["group"].isin(groups)].copy()
    s["y"] = s["group"].map(lab)
    s["is_f"] = (s["sex"] == "F").astype(float)
    per_fold = []
    for fold in split["folds"]:
        tr = s.loc[fold["train_subjects"]]
        te = s.loc[fold["test_subjects"]]
        clf = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))
        clf.fit(tr[features].values, tr["y"].values)
        pred = clf.predict(te[features].values)
        prob = clf.predict_proba(te[features].values)
        m = {"acc": accuracy_score(te["y"], pred), "bacc": balanced_accuracy_score(te["y"], pred),
             "macro_f1": f1_score(te["y"], pred, average="macro")}
        m["auc"] = (roc_auc_score(te["y"], prob[:, 1]) if len(groups) == 2
                    else roc_auc_score(te["y"], prob, multi_class="ovr", average="macro"))
        per_fold.append(m)
    keys = per_fold[0].keys()
    return {k: {"mean": float(np.mean([f[k] for f in per_fold])),
                "sd": float(np.std([f[k] for f in per_fold])),
                "folds": [float(f[k]) for f in per_fold]} for k in keys}


def main():
    repo = sys.argv[1]
    df, subj = subject_table(os.path.join(repo, "labels.csv"))
    out = {"demographics": demographics(df, subj), "baselines": {}}
    for task in TASKS:
        for name, feats in [("age", ["age_first"]), ("age+sex", ["age_first", "is_f"])]:
            out["baselines"][f"{task}/{name}"] = baseline(subj, os.path.join(repo, "splits"), task, feats)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cohort_age_baseline.json")
    json.dump(out, open(path, "w"), indent=2)
    d = out["demographics"]
    print(json.dumps({k: v for k, v in d.items() if k != "groups"}, indent=1))
    for g, v in d["groups"].items():
        print(g, {k: round(x, 2) if isinstance(x, float) else x for k, x in v.items()})
    for k, v in out["baselines"].items():
        print(f"{k:16s} " + "  ".join(f"{m}={v[m]['mean']:.3f}±{v[m]['sd']:.3f}" for m in v))


if __name__ == "__main__":
    main()
