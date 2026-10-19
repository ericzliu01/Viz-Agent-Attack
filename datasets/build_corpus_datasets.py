"""Build datasets/corpus_datasets.json: the datasets the original attack
corpus (build_dataset_pages.py) is copied onto, computed from the CSVs.

Each view below was chosen because it meets the chart type's shape rules
(see build_dataset_pages.py), which the corpus's task truths and attack
premises depend on. Charts with no real view that meets them are left out
and listed in notes/real_corpus_fit.md:
  scatter: public_health and steam (no pair of real series where one
           strictly rises and the other strictly falls over >= 6 x values)
  line, stacked_bar: public_health (the only rising pairs are prevalence
           percentages, which the line tasks' "how many" wording can't ask
           about; the stacked fit only works by sorting states by total)
The revenue chart type (reasoning attacks) keeps the dummy entries from
dummy_datasets.json: its pages and attacks are written around quarterly
revenue by region.

Usage (repo root): python datasets/build_corpus_datasets.py && python build_dataset_pages.py
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "corpus_datasets.json")
LIVER = "Chronic liver disease mortality among all people, underlying cause"


def ints(values):
    return [int(round(float(v))) for v in values]


def years_x(years):
    labels = [str(y) for y in years]
    return {"labels": labels, "full": labels, "noun": "year", "plural": "years", "title": "Year", "prep": "in"}


def climate(c):
    by = c.set_index(["country", "year"])
    bar_countries = ["China", "United States", "India", "Russia", "Japan"]
    line_years = list(range(2015, 2021))
    scatter_years = list(range(2002, 2023, 4))
    stack_years = list(range(2013, 2018))
    china = by.loc["China"]
    return {
        "bar": {
            "id": "climate_core", "title": "CO2 Emissions by Country", "subtitle": "2022, five largest emitters, million tonnes",
            "period": "in 2022",
            "category": {"word": "country", "plural": "countries", "title": "Country"},
            "value": {"word": "megatonnes", "title": "Megatonnes"},
            "categories": bar_countries,
            "values": ints(by.loc[(n, 2022), "co2"] for n in bar_countries),
        },
        "line": {
            "id": "climate_core", "title": "Annual CO2 Emissions", "subtitle": "India vs Iran, 2015&ndash;2020, million tonnes",
            "x": years_x(line_years),
            "period": {"noun": "period", "adj": "yearly", "phrase": "over 2015-2020", "over": "year over year"},
            "measure": {"plural": "megatonnes", "metric": "annual emissions", "short": "megatonnes",
                        "short_title": "Megatonnes", "axis_title": "CO2 (million tonnes)", "abbr": "CO2"},
            "group": {"word": "country", "title": "Country"},
            "series": [{"name": n, "values": ints(by.loc[(n, y), "co2"] for y in line_years)}
                       for n in ("India", "Iran")],
        },
        "scatter": {
            "id": "climate_core", "title": "CO2 per Capita by Year", "subtitle": "China vs Germany, every fourth year, tonnes per person",
            "x": {"values": scatter_years, "word": "year", "title": "Year", "axis_title": "Year", "phrase": "year",
                  "level": "year", "levels": "years", "at": "the year", "gloss": "(tonnes of CO2 per person)"},
            "group": {"word": "country", "plural": "countries", "title": "Country"},
            "value": {"word": "tonnes", "title": "Tonnes", "singular": "tonne"},
            "series": [{"name": n, "values": [round(float(by.loc[(n, y), "co2_per_capita"]), 2) for y in scatter_years]}
                       for n in ("China", "Germany")],
        },
        "stacked_bar": {
            "id": "climate_core", "title": "China CO2 by Fuel Source", "subtitle": "Cement / Oil / Gas, stacked, million tonnes",
            "summary_label": "China CO2",
            "category": {"labels": [str(y) for y in stack_years], "word": "year", "plural": "years", "title": "Year",
                         "adj": "yearly", "prep": "in", "span": "the five years"},
            "group": {"word": "source", "plural": "sources", "title": "Source", "phrase": "fuel sources"},
            "value": {"word": "megatonnes", "title": "Megatonnes"},
            "series": [{"name": name, "values": ints(china.loc[y, col] for y in stack_years)}
                       for name, col in (("Cement", "cement_co2"), ("Oil", "oil_co2"), ("Gas", "gas_co2"))],
        },
    }


def public_health(p):
    deaths = p[(p.question == LIVER) & (p.datavaluetype == "Number") & (p.stratificationcategory1 == "Overall")
               & (p.yearstart == 2022)].set_index("locationdesc").datavalue
    states = ["California", "Texas", "Florida", "Ohio", "New York"]
    return {
        "bar": {
            "id": "public_health_core", "title": "Chronic Liver Disease Deaths by State",
            "subtitle": "2022, five states with the most deaths", "period": "in 2022",
            "category": {"word": "state", "plural": "states", "title": "State"},
            "value": {"word": "deaths", "title": "Deaths"},
            "categories": states, "values": ints(deaths[s] for s in states),
        },
    }


def steam(s):
    s = s.assign(year=pd.to_datetime(s.release_date, errors="coerce").dt.year,
                 genre=s.genres.str.split(";").str[0])
    total = s.positive_ratings + s.negative_ratings
    share = s.positive_ratings / total.where(total > 0)
    s["tier"] = share.map(lambda v: "Positive" if v >= 0.8 else "Mixed" if v >= 0.4 else "Negative")
    bar_genres = ["Action", "Adventure", "Casual", "Indie", "Simulation"]
    per_genre = s[s.year.between(2015, 2018)].groupby("genre").size()
    line_years = list(range(2012, 2019))
    releases = s.groupby(["genre", "year"]).size()
    stack_years = list(range(2010, 2016))
    tiers = s.groupby(["tier", "year"]).size()
    return {
        "bar": {
            "id": "steam_core", "title": "Steam Games by Genre", "subtitle": "released 2015&ndash;2018, first listed genre",
            "period": "in 2015-2018",
            "category": {"word": "genre", "plural": "genres", "title": "Genre"},
            "value": {"word": "games", "title": "Games"},
            "categories": bar_genres, "values": ints(per_genre[g] for g in bar_genres),
        },
        "line": {
            "id": "steam_core", "title": "Steam Games Released per Year", "subtitle": "Strategy vs Simulation, 2012&ndash;2018",
            "x": years_x(line_years),
            "period": {"noun": "period", "adj": "yearly", "phrase": "over 2012-2018", "over": "year over year"},
            "measure": {"plural": "releases", "metric": "yearly releases", "short": "releases",
                        "short_title": "Releases", "axis_title": "Games released", "abbr": "releases"},
            "group": {"word": "genre", "title": "Genre"},
            "series": [{"name": g, "values": ints(releases.get((g, y), 0) for y in line_years)}
                       for g in ("Strategy", "Simulation")],
        },
        "stacked_bar": {
            "id": "steam_core", "title": "Steam Releases by Review Rating",
            "subtitle": "Mixed (40-79% positive) / Positive (80%+) / Negative (under 40%), stacked",
            "summary_label": "Steam releases",
            "category": {"labels": [str(y) for y in stack_years], "word": "year", "plural": "years", "title": "Year",
                         "adj": "yearly", "prep": "in", "span": "the six years"},
            "group": {"word": "rating", "plural": "ratings", "title": "Rating", "phrase": "review ratings"},
            "value": {"word": "games", "title": "Games"},
            "series": [{"name": t, "values": ints(tiers.get((t, y), 0) for y in stack_years)}
                       for t in ("Mixed", "Positive", "Negative")],
        },
    }


def main():
    c = pd.read_csv(os.path.join(HERE, "climate.csv"))
    p = pd.read_csv(os.path.join(HERE, "public_health.csv"), low_memory=False)
    s = pd.read_csv(os.path.join(HERE, "steam.csv"))
    parts = [climate(c), public_health(p), steam(s)]
    with open(os.path.join(HERE, "dummy_datasets.json"), encoding="utf-8") as fh:
        revenue = json.load(fh)["revenue"]
    out = {"_comment": "Real datasets for the original attack corpus, computed from the CSVs by "
                       "datasets/build_corpus_datasets.py (views and gaps in its docstring). revenue keeps the "
                       "dummy entries. Run `python build_dataset_pages.py` after rebuilding."}
    for chart_type in ("bar", "line", "scatter", "stacked_bar"):
        out[chart_type] = [part[chart_type] for part in parts if chart_type in part]
    out["revenue"] = revenue
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
