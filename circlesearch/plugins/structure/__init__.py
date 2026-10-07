import csv
import io
from dataclasses import dataclass

from circlesearch.core import layout
from circlesearch.core.cards import Action, Card
from circlesearch.core.layout import Table
from circlesearch.core.pipeline import resolver


@dataclass(kw_only=True)
class TableCard(Card):
    kind = "table"
    priority = 1

    table: Table


@layout.layout("table", order=10)
def find_table(text, words):
    return layout.table(words)


def as_csv(table):
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(table.rows)
    return out.getvalue().rstrip("\n")


@resolver("table")
def table_card(route):
    table = route.value
    return TableCard(title=f"{len(table.rows)} rows × {table.columns} columns", table=table,
                     actions=[Action("Copy for spreadsheet", "copy", table.tsv()),
                              Action("Markdown", "copy", table.markdown()), Action("CSV", "copy", as_csv(table))])
