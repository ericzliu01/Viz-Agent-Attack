"""Image-mode prompts for the Xu & Wall benchmark.

The original prompts (llm/prompts.json) send the chart as SVG source and, for
seven tasks, ask for an edited SVG back. Here the model gets the same chart
rendered to PNG, so every task asks for a text answer instead:

  retrieval, derive, range, distribution   same answer format as the original
  filter, extreme, anomaly                 CSV of the selected points or bins (X, Y)
  sort                                     CSV of all bin heights, descending
  cluster                                  CSV of every point with a cluster id
  correlate                                'slope, intercept' of the regression line

Task definitions and criteria keep the original wording (e.g. "(Y > 0)",
"(X >= 2 and X <= 6)", "the one outlier", "the two outlier points").
SVG-specific instructions (top-left origin, flipping y) are dropped.
"""
import items as I

NOUN = {"scatter": "scatter plot", "line": "line chart", "bar": "bar plot"}
UNIT = {"scatter": "points", "line": "data points", "bar": "bins"}

NO_EXTRA = "Do not include any other textual answer in your response."


def _input(chart, labeled):
    s = f"<input>: An image of a {NOUN[chart]} with n {UNIT[chart]}."
    if chart == "bar":
        s += (" Each bin is labeled with its corresponding X and Y values." if labeled
              else " The bins are not labeled with their values.")
    else:
        s += (" Each data point is labeled with its corresponding coordinates (X and Y values)." if labeled
              else " The points are not labeled with their coordinates.")
    s += " The axes are labeled with their respective scales."
    return s


def _read_step(chart, labeled):
    what = "bin" if chart == "bar" else "data point"
    if labeled:
        return f"Examine the {NOUN[chart]} image and read the X and Y values of each {what} from its label."
    return (f"Examine the {NOUN[chart]} image, identify the axes and their scales, and read the X and Y "
            f"values of each {what} from its position relative to the axes.")


def _csv_rows(chart, what):
    return (f"A comma-separated values (CSV) string with two columns: 'X' and 'Y', with one row for each "
            f"{what}. Give values in data units as shown on the axes. {NO_EXTRA}")


def task_spec(chart, task):
    """(output description, task steps) for one chart type and task."""
    u = UNIT[chart]
    one = "bin" if chart == "bar" else "data point"
    if task == "retrieval":
        if chart == "bar":
            return (f"A comma-separated values (CSV) string with one column: 'Y'. Each row represents the height "
                    f"of a bin, from left to right. {NO_EXTRA}", ["Format the heights as a CSV string with one column 'Y'."])
        return (f"A comma-separated values (CSV) string with two columns: 'X' and 'Y'. Each row represents the "
                f"coordinates of a data point. {NO_EXTRA}", ["Format the coordinates as a CSV string with two columns 'X' and 'Y'."])
    if task == "derive":
        return (f"A single numerical value representing the computed aggregate (mean of the Y values). {NO_EXTRA}",
                ["Calculate the mean of all the Y values."])
    if task == "range":
        return (f"The range of the Y values in the dataset, in the format of 'min, max'. {NO_EXTRA}",
                ["Determine the minimum and maximum values among the Y values."])
    if task == "distribution":
        return (f"A single phrase describing the type of distribution observed in the {NOUN[chart]}, the answer "
                f"should be one of [normal, uniform, binomial]. {NO_EXTRA}",
                [f"Analyze the overall pattern and distribution of the {u} in the {NOUN[chart]}.",
                 "Determine the type of distribution that best describes the data."])
    if task == "filter":
        crit = {"scatter": "(Y > 0)", "line": "(X >= 2 and X <= 6)", "bar": "(X >= 3 and X <= 7)"}[chart]
        return (_csv_rows(chart, f"{one} that meets the criteria {crit}"),
                [f"Apply the specified filtering criteria: {crit}.",
                 f"List only the {u} that meet the criteria."])
    if task == "extreme":
        return (_csv_rows(chart, f"extremum {one}"),
                [f"Identify the extremum {u}, defined as the {u} with the highest and lowest Y values.",
                 f"List only the extremum {u}."])
    if task == "anomaly":
        what = {"scatter": "the one outlier in the scatter plot, defined as the data point that significantly "
                           "deviates from the clusters",
                "line": "the two outlier points in the line chart, defined as data points that represent "
                        "significant spikes or drops",
                "bar": "the outlier bins in the bar plot, defined as bins that represent significant spikes or drops"}[chart]
        return (_csv_rows(chart, "outlier " + one),
                [f"Identify {what}.", f"List only the outlier {u}."])
    if task == "sort":
        return (f"A comma-separated values (CSV) string with one column: 'Y'. The rows are the heights of all n "
                f"bins sorted in descending order. {NO_EXTRA}",
                ["Sort the bins in descending order based on their Y values (heights).",
                 "Keep every bin, so the output has the same number of rows as there are bins."])
    if task == "cluster":
        return (f"A comma-separated values (CSV) string with three columns: 'X', 'Y' and 'Cluster', with one row "
                f"for each data point. 'Cluster' is an integer cluster id. {NO_EXTRA}",
                ["Cluster the points into distinct groups based on their proximity or similarity.",
                 "Give points in the same cluster the same id and points in different clusters different ids.",
                 "Include every data point."])
    if task == "correlate":
        return (f"The slope and intercept of the fitted line, in the format of 'slope, intercept', in data units. "
                f"{NO_EXTRA}",
                ["Perform linear regression (least squares, Y on X) on the X and Y values to obtain the "
                 "coefficients of the fitted line."])
    raise ValueError(task)


def build_image_prompt(chart, cond, task):
    labeled = I.label_of(cond) == "labeled"
    out, steps = task_spec(chart, task)
    steps = [_read_step(chart, labeled)] + steps + ["Provide only the answer in the output format, without any additional textual answer."]
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    return f"{_input(chart, labeled)}\n\n<output>: {out}\n\nInstructions:\n{body}\n\n<input {NOUN[chart]} image>:"


def png_path(png_root, repo, chart, cond, task, idx):
    """PNG rendered from the item's SVG, at the same relative path under png_root."""
    import os
    rel = os.path.relpath(I.image_path(repo, chart, cond, task, idx), repo)
    return os.path.join(png_root, rel[:-4] + ".png")
