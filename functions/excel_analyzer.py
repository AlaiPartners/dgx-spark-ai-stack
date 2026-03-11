"""
Open WebUI Tool: Excel Analyzer
--------------------------------
Install in Open WebUI:
  Settings → Tools → + New Tool → paste this entire file

The model will call these functions when a user uploads a spreadsheet
and asks questions about it. Pass the filename shown in the upload UI
(e.g. "sales_q3.xlsx") -- the sidecar resolves it from the uploads volume.
"""

import requests
from pydantic import BaseModel, Field
from typing import Optional

SIDECAR_URL = "http://excel-sidecar:9000"


class Tools:

    def analyze_spreadsheet(
        self,
        filename: str,
        sheet: Optional[str] = None,
    ) -> str:
        """
        Analyze an uploaded Excel or CSV file. Returns shape, column names,
        data types, null counts, and numeric summary statistics.
        Use this first when a user uploads a spreadsheet to understand its structure.

        :param filename: The uploaded filename (e.g. 'sales.xlsx')
        :param sheet: Optional sheet name for multi-sheet Excel files
        """
        try:
            r = requests.post(
                f"{SIDECAR_URL}/analyze",
                json={"filename": filename, "sheet": sheet},
                timeout=30,
            )
            r.raise_for_status()
            return r.text
        except Exception as e:
            return f"Error analyzing file: {e}"

    def query_spreadsheet(
        self,
        filename: str,
        sheet: Optional[str] = None,
        columns: Optional[list] = None,
        filters: Optional[dict] = None,
        group_by: Optional[str] = None,
        agg: Optional[str] = "sum",
        limit: int = 50,
    ) -> str:
        """
        Fetch raw rows from a spreadsheet with optional column selection and
        simple equality filtering. Returns JSON rows only -- does NOT compute
        averages, ratios, or multi-step calculations.
        Use this ONLY to retrieve or preview data rows.
        For any calculation (average, ratio, percentage, ranked list, filtered
        aggregation, or custom logic), use execute_spreadsheet_query instead.

        :param filename: The uploaded filename
        :param sheet: Optional sheet name
        :param columns: List of column names to include (e.g. ['Region', 'Revenue'])
        :param filters: Dict of exact-match filters (e.g. {'Region': 'West'})
        :param group_by: Column name to group by
        :param agg: Aggregation to apply when grouping: sum, mean, count, min, max
        :param limit: Max rows to return (default 50)
        """
        try:
            r = requests.post(
                f"{SIDECAR_URL}/query",
                json={
                    "filename": filename,
                    "sheet": sheet,
                    "columns": columns,
                    "filters": filters,
                    "group_by": group_by,
                    "agg": agg,
                    "limit": limit,
                },
                timeout=30,
            )
            r.raise_for_status()
            return r.text
        except Exception as e:
            return f"Error querying file: {e}"

    def spreadsheet_to_markdown(
        self,
        filename: str,
        sheet: Optional[str] = None,
        columns: Optional[list] = None,
        filters: Optional[dict] = None,
        limit: int = 30,
    ) -> str:
        """
        Convert an uploaded Excel or CSV file to a markdown table for display.
        Use this when the user wants to see the data rendered as a readable table.
        Caps at `limit` rows to avoid overwhelming the context window.

        :param filename: The uploaded filename
        :param sheet: Optional sheet name
        :param columns: Columns to include
        :param filters: Row filters to apply before rendering
        :param limit: Max rows to show (default 30)
        """
        try:
            r = requests.post(
                f"{SIDECAR_URL}/to-markdown",
                json={
                    "filename": filename,
                    "sheet": sheet,
                    "columns": columns,
                    "filters": filters,
                    "limit": limit,
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("markdown", "No data returned.")
        except Exception as e:
            return f"Error rendering table: {e}"

    def execute_spreadsheet_query(
        self,
        filename: str,
        question: str,
        sheet: Optional[str] = None,
    ) -> str:
        """
        Use this tool to answer ANY analytical or computational question about
        a spreadsheet. This is the correct tool for: averages, ratios, sums,
        counts, percentages, rankings, filtered aggregations, multi-step
        calculations, and any question where you need to compute a result.
        ALWAYS prefer this over query_spreadsheet when the user asks a question
        that requires math or aggregation.
        Examples:
          - "average tenants per unit by calc type"
          - "total revenue for properties in Denver"
          - "which property has the highest rent per sqft"
          - "what percentage of properties use RUBS"

        :param filename: The uploaded filename (e.g. 'data.xlsx')
        :param question: The analytical question to answer in plain English
        :param sheet: Optional sheet name for multi-sheet Excel files
        """
        try:
            r = requests.post(
                f"{SIDECAR_URL}/execute",
                json={"filename": filename, "question": question, "sheet": sheet},
                timeout=90,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("success"):
                return f"Result: {data['result']}\n\nGenerated code:\n```python\n{data['code']}\n```"
            else:
                return (
                    f"The computation failed after two attempts. "
                    f"Error: {data.get('error')}\n"
                    f"Last generated code:\n```python\n{data.get('code')}\n```\n"
                    f"Please tell the user what went wrong and suggest rephrasing the question."
                )
        except Exception as e:
            return f"Error executing query: {e}"
