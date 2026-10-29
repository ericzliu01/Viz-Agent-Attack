"""Build datasets/real_datasets.json from the CSVs in datasets/.

Each chart's numbers are computed here from climate.csv, public_health.csv
and steam.csv, so the charts can be checked against (and regenerated from)
the raw data. Run from the repo root, then rebuild the pages:

    python datasets/build_real_datasets.py
    python build_dataset_pages.py

Selection rules (what each chart shows):
  climate        bar: the 10 countries with the highest total CO2 in 2022.
                 line: CO2 per capita 1990-2022 for Brazil, China, Germany,
                 India and the United States.
                 scatter: GDP per capita (gdp / population) vs CO2 per capita,
                 2022, every country with both values (OWID aggregates such as
                 "World" have no iso_code or an OWID_ code and are left out).
                 stacked_bar: US CO2 by source 1990-2022 (cement, coal,
                 flaring, gas, land-use change, oil; "other industry" is not
                 shown).
  public_health  "Chronic liver disease mortality among all people, underlying
                 cause", crude rate per 100,000.
                 bar: 2022, the 10 most populous states (population taken as
                 deaths / crude rate x 100,000, since the CSV has no
                 population column), alphabetical.
                 line: 2019-2022, the 5 most populous states.
                 scatter: 2022, male vs female rate per state (DC included,
                 the United States total left out).
                 stacked_bar: 2022, female and male rate for the line's 5
                 states.
  steam          games are assigned to the first genre listed; release year
                 from release_date.
                 bar: mean price by genre, 2015-2018, for the 10 genres in
                 GENRES.
                 line: mean positive ratings per game by release year,
                 2010-2018.
                 scatter: achievements vs average playtime for the 300 games
                 pinned in steam_scatter_sample.json.
                 stacked_bar: games per release year 2010-2018 by review
                 tier: share of positive ratings >= 0.8 Very Positive,
                 >= 0.6 Mostly Positive, >= 0.4 Mixed, else Negative.
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "real_datasets.json")
LINE_COUNTRIES = ["Brazil", "China", "Germany", "India", "United States"]
US_SOURCES = [("Cement", "cement_co2"), ("Coal", "coal_co2"), ("Flaring", "flaring_co2"), ("Gas", "gas_co2"),
              ("Land Use Change", "land_use_change_co2"), ("Oil", "oil_co2")]
LIVER = "Chronic liver disease mortality among all people, underlying cause"
GENRES = ["Action", "Adventure", "Casual", "Indie", "Massively Multiplayer", "RPG", "Racing", "Simulation",
          "Sports", "Strategy"]
TIERS = ["Mixed", "Mostly Positive", "Negative", "Very Positive"]


def r(values, digits=3):
    return [round(float(v), digits) for v in values]


def climate():
    c = pd.read_csv(os.path.join(HERE, "climate.csv"))
    countries = c[c.iso_code.notna() & ~c.iso_code.astype(str).str.startswith("OWID")]
    y22 = countries[countries.year == 2022]
    top = y22.nlargest(10, "co2").sort_values("country")
    line = c[c.country.isin(LINE_COUNTRIES) & c.year.between(1990, 2022)]
    years = sorted(line.year.unique())
    sc = y22[y22.co2_per_capita.notna() & y22.gdp.notna()]
    us = c[(c.country == "United States") & c.year.between(1990, 2022)].sort_values("year")
    return {
        "source": "datasets/climate.csv",
        "bar": {"title": "Total CO2 Emissions by Country (2022)", "x_title": "Country",
                "y_title": "CO2 (million tonnes)", "labels": top.country.tolist(), "values": r(top.co2)},
        "line": {"title": "CO2 per Capita Over Time (1990-2022)", "x_title": "Year",
                 "y_title": "CO2 per capita (tonnes)", "labels": [str(y) for y in years],
                 "series": [{"name": name, "values": r(line[line.country == name].sort_values("year").co2_per_capita)}
                            for name in LINE_COUNTRIES]},
        "scatter": {"title": "GDP per Capita vs CO2 per Capita (2022)", "x_title": "GDP per capita (USD)",
                    "y_title": "CO2 per capita (tonnes)",
                    "points": [[round(g / p, 1), round(y, 3)]
                               for g, p, y in zip(sc.gdp, sc.population, sc.co2_per_capita)]},
        "stacked_bar": {"title": "US CO2 by Fuel Source (1990-2022)", "x_title": "Year",
                        "y_title": "CO2 (million tonnes)", "labels": [str(y) for y in us.year],
                        "series": [{"name": name, "values": r(us[col])} for name, col in US_SOURCES]},
    }


def public_health():
    p = pd.read_csv(os.path.join(HERE, "public_health.csv"), low_memory=False)
    liver = p[p.question == LIVER]
    rate = liver[liver.datavaluetype == "Crude Rate"]
    deaths = liver[(liver.datavaluetype == "Number") & (liver.stratificationcategory1 == "Overall")
                   & (liver.yearstart == 2022) & (liver.locationdesc != "United States")]
    overall = rate[rate.stratificationcategory1 == "Overall"]
    bar = overall[overall.yearstart == 2022].set_index("locationdesc").datavalue
    population = (deaths.set_index("locationdesc").datavalue / bar * 1e5).dropna()
    by_population = population.sort_values(ascending=False).index.tolist()
    bar_states = sorted(by_population[:10])
    line_states = sorted(by_population[:5])
    sex = rate[(rate.stratificationcategory1 == "Sex") & (rate.yearstart == 2022)
               & (rate.locationdesc != "United States")]
    by_sex = sex.pivot_table(index="locationdesc", columns="stratification1", values="datavalue").dropna()
    return {
        "source": "datasets/public_health.csv",
        "bar": {"title": "Chronic Liver Disease Mortality by State (2022)", "x_title": "State",
                "y_title": "Crude rate (per 100,000)", "labels": bar_states,
                "values": r(bar[s] for s in bar_states)},
        "line": {"title": "Chronic Liver Disease Mortality Over Time (Top 5 States)", "x_title": "Year",
                 "y_title": "Crude rate (per 100,000)", "labels": ["2019", "2020", "2021", "2022"],
                 "series": [{"name": s, "values": r(overall[overall.locationdesc == s].sort_values("yearstart").datavalue)}
                            for s in line_states]},
        "scatter": {"title": "Male vs Female Chronic Liver Disease Mortality by State (2022)",
                    "x_title": "Male crude rate (per 100,000)", "y_title": "Female crude rate (per 100,000)",
                    "points": [[round(m, 1), round(f, 1)] for m, f in zip(by_sex.Male, by_sex.Female)]},
        "stacked_bar": {"title": "Chronic Liver Disease Mortality by Sex and State (2022)", "x_title": "State",
                        "y_title": "Crude rate (per 100,000)", "labels": line_states,
                        "series": [{"name": sx, "values": r(by_sex.loc[line_states, sx])}
                                   for sx in ("Female", "Male")]},
    }


def tier(share):
    if pd.isna(share):
        return "Negative"
    return "Very Positive" if share >= 0.8 else "Mostly Positive" if share >= 0.6 else \
        "Mixed" if share >= 0.4 else "Negative"


def steam():
    s = pd.read_csv(os.path.join(HERE, "steam.csv"))
    s["year"] = pd.to_datetime(s.release_date, errors="coerce").dt.year
    s["genre"] = s.genres.str.split(";").str[0]
    price = s[s.year.between(2015, 2018)].groupby("genre").price.mean()
    by_year = s[s.year.between(2010, 2018)]
    ratings = by_year.groupby("year").positive_ratings.mean()
    total = s.positive_ratings + s.negative_ratings
    s["tier"] = (s.positive_ratings / total.where(total > 0)).map(tier)
    counts = s[s.year.between(2010, 2018)].groupby(["tier", "year"]).size().unstack(fill_value=0)
    with open(os.path.join(HERE, "steam_scatter_sample.json"), encoding="utf-8") as fh:
        appids = json.load(fh)["appids"]
    sample = s.set_index("appid").loc[appids]
    years = [str(int(y)) for y in ratings.index]
    return {
        "source": "datasets/steam.csv",
        "bar": {"title": "Average Price by Genre (2015-2018)", "x_title": "Genre", "y_title": "Mean price (USD)",
                "labels": GENRES, "values": r(price[g] for g in GENRES)},
        "line": {"title": "Average Positive Ratings per Game by Release Year", "x_title": "Release Year",
                 "y_title": "Mean positive ratings", "labels": years,
                 "series": [{"name": "Mean positive ratings", "values": r(ratings)}]},
        "scatter": {"title": "Achievements vs Average Playtime", "x_title": "Number of achievements",
                    "y_title": "Average playtime (minutes)",
                    "points": [[float(a), float(t)] for a, t in zip(sample.achievements, sample.average_playtime)]},
        "stacked_bar": {"title": "Game Releases by Review Tier (2010-2018)", "x_title": "Release Year",
                        "y_title": "Number of games", "labels": years,
                        "series": [{"name": t, "values": r(counts.loc[t].reindex(range(2010, 2019), fill_value=0))}
                                   for t in TIERS]},
    }


def main():
    out = {"_comment": "Chart data for the real datasets, computed from the CSVs by "
                       "datasets/build_real_datasets.py (selection rules in its docstring). "
                       "build_real_dataset_pages.py turns each entry plus its tasks in "
                       "tasks/extended_tasks.json into clean and attack pages. social_media has no CSV or "
                       "tasks yet and is not included.",
           "climate": climate(), "public_health": public_health(), "steam": steam()}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
