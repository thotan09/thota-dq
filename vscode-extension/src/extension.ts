import * as vscode from "vscode";

// ---------------------------------------------------------------------------
// Hover documentation
// ---------------------------------------------------------------------------

const RULE_TYPE_DOCS: Record<string, { summary: string; fields: string }> = {
  not_null: {
    summary: "Column must not contain NULL values.",
    fields: "No additional fields required.",
  },
  not_empty_string: {
    summary: "Column must not contain empty or whitespace-only strings.",
    fields: "No additional fields required.",
  },
  null_percentage_below: {
    summary: "NULL values must represent less than `threshold`% of rows.",
    fields: "`threshold` (number, required) — max allowed NULL percentage.",
  },
  unique: {
    summary: "Column values must be unique across the table.",
    fields: "No additional fields required.",
  },
  composite_unique: {
    summary: "Combination of specified `columns` must be unique.",
    fields: "List all columns in `scope.columns`.",
  },
  duplicate_percentage_below: {
    summary: "Duplicate values must represent less than `threshold`% of rows.",
    fields: "`threshold` (number, required) — max allowed duplicate percentage.",
  },
  sql_expression: {
    summary: "Rows must satisfy a SQL WHERE expression to PASS.",
    fields: "`expression` (string, required) — SQL WHERE clause applied to each row.",
  },
  between: {
    summary: "Column values must fall between `min_value` and `max_value` (inclusive).",
    fields: "`min_value` (number, required), `max_value` (number, required).",
  },
  min_value_check: {
    summary: "Column values must be >= `threshold`.",
    fields: "`threshold` (number, required) — minimum allowed value.",
  },
  max_value_check: {
    summary: "Column values must be <= `threshold`.",
    fields: "`threshold` (number, required) — maximum allowed value.",
  },
  regex_match: {
    summary: "Column values must match a regular expression `pattern`.",
    fields: "`pattern` (string, required) — regex pattern (unanchored unless you add ^ / $).",
  },
  accepted_values: {
    summary: "Column values must belong to the `values` list.",
    fields: "`values` (list of strings, required) — allowed value set.",
  },
  not_accepted_values: {
    summary: "Column values must NOT appear in the `values` list.",
    fields: "`values` (list of strings, required) — prohibited value set.",
  },
  no_future_dates: {
    summary: "Date/timestamp column must not contain dates in the future.",
    fields: "No additional fields required.",
  },
  column_exists: {
    summary: "Specified column must exist in the table schema.",
    fields: "Specify the column in `scope.columns`.",
  },
  foreign_key: {
    summary: "Column values must exist in `reference_table.reference_column`.",
    fields:
      "`reference_table` (string, required), `reference_column` (string, required).",
  },
  conditional_not_null: {
    summary: "Column must not be NULL when `condition` evaluates to true.",
    fields: "`condition` (string, required) — SQL expression that triggers the check.",
  },
  mean_between: {
    summary: "Column mean must fall between `min_value` and `max_value`.",
    fields: "`min_value` (number, required), `max_value` (number, required).",
  },
  stddev_below: {
    summary: "Column standard deviation must not exceed `threshold`.",
    fields: "`threshold` (number, required).",
  },
  column_sum_between: {
    summary: "Column sum must fall between `min_value` and `max_value`.",
    fields: "`min_value` (number, required), `max_value` (number, required).",
  },
  freshness: {
    summary: "Table must have been updated within the last `threshold` hours.",
    fields:
      "`threshold` (number, required) — max staleness. `unit` defaults to `hours`.",
  },
  date_order: {
    summary: "First date column must be <= `column_b`.",
    fields: "`column_b` (string, required) — the later-date column.",
  },
  row_count: {
    summary: "Table must contain at least `threshold` rows.",
    fields: "`threshold` (number, required) — minimum row count.",
  },
  row_count_between: {
    summary: "Table row count must be between `min_value` and `max_value`.",
    fields: "`min_value` (number, required), `max_value` (number, required).",
  },
  custom_sql: {
    summary:
      "Run a fully custom SQL query. Must return a single row with columns `passed` (BOOLEAN) and `row_count` (INT).",
    fields: "`query` (string, required) — full SQL statement.",
  },
  row_count_match: {
    summary:
      "Target table and `source_table` must have the same row count (within `tolerance_pct`%).",
    fields:
      "`source_table` (string, required), `tolerance_pct` (number, default 0).",
  },
  column_sum_match: {
    summary:
      "Column sum must match between target and `source_table` (within `tolerance_pct`%).",
    fields:
      "`source_table` (string, required), `tolerance_pct` (number, default 0).",
  },
  set_inclusion: {
    summary:
      "All values in the target column must exist in `reference_table.reference_column`.",
    fields:
      "`reference_table` (string, required), `reference_column` (string, required).",
  },
  set_equality: {
    summary:
      "Value sets must be identical between target column and `reference_table.reference_column`.",
    fields:
      "`reference_table` (string, required), `reference_column` (string, required).",
  },
};

const SEVERITY_DOCS: Record<string, string> = {
  critical: "Immediate action required. Blocks pipeline or triggers on-call page.",
  high: "Significant data quality issue — investigate within 1 business day.",
  medium: "Notable issue — review in next sprint.",
  low: "Minor deviation — log and monitor.",
  info: "Informational only — no action required.",
};

function makeHoverMarkdown(title: string, body: string): vscode.Hover {
  const md = new vscode.MarkdownString();
  md.appendMarkdown(`**${title}**\n\n${body}`);
  md.isTrusted = true;
  return new vscode.Hover(md);
}

function buildHoverProvider(): vscode.HoverProvider {
  return {
    provideHover(
      document: vscode.TextDocument,
      position: vscode.Position
    ): vscode.Hover | undefined {
      const config = vscode.workspace.getConfiguration("aegisDQ");
      if (!config.get<boolean>("hoverDocs", true)) return undefined;

      const line = document.lineAt(position).text;
      const wordRange = document.getWordRangeAtPosition(position, /[\w_]+/);
      if (!wordRange) return undefined;
      const word = document.getText(wordRange);

      // Hover on a type: value line
      if (/type:\s*/.test(line) && RULE_TYPE_DOCS[word]) {
        const doc = RULE_TYPE_DOCS[word];
        return makeHoverMarkdown(
          `Rule type: \`${word}\``,
          `${doc.summary}\n\n**Required fields:** ${doc.fields}`
        );
      }

      // Hover on a severity: value line
      if (/severity:\s*/.test(line) && SEVERITY_DOCS[word]) {
        return makeHoverMarkdown(
          `Severity: \`${word}\``,
          SEVERITY_DOCS[word]
        );
      }

      // Hover on the key "type" itself — list all rule types
      if (word === "type" && /^\s+type:\s*$/.test(line)) {
        const types = Object.keys(RULE_TYPE_DOCS).join(", ");
        return makeHoverMarkdown(
          "logic.type",
          `Specifies which rule to run. Available types:\n\n\`${types}\``
        );
      }

      return undefined;
    },
  };
}

// ---------------------------------------------------------------------------
// Validate command
// ---------------------------------------------------------------------------

async function validateCurrentFile(
  diagnosticCollection: vscode.DiagnosticCollection
): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Aegis DQ: No active file to validate.");
    return;
  }

  const doc = editor.document;
  const text = doc.getText();
  const diagnostics: vscode.Diagnostic[] = [];

  // Light structural checks without a full YAML parser dependency
  const lines = text.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Check for type: value that isn't in our known set
    const typeMatch = trimmed.match(/^type:\s+(\S+)/);
    if (typeMatch) {
      const ruleType = typeMatch[1];
      if (!RULE_TYPE_DOCS[ruleType]) {
        const col = line.indexOf(ruleType);
        const range = new vscode.Range(i, col, i, col + ruleType.length);
        diagnostics.push(
          new vscode.Diagnostic(
            range,
            `Unknown rule type '${ruleType}'. Run 'aegis rules list' to see all 28 types.`,
            vscode.DiagnosticSeverity.Error
          )
        );
      }
    }

    // Check for severity: value that isn't valid
    const sevMatch = trimmed.match(/^severity:\s+(\S+)/);
    if (sevMatch) {
      const sev = sevMatch[1];
      if (!SEVERITY_DOCS[sev]) {
        const col = line.indexOf(sev);
        const range = new vscode.Range(i, col, i, col + sev.length);
        diagnostics.push(
          new vscode.Diagnostic(
            range,
            `Invalid severity '${sev}'. Must be one of: critical, high, medium, low, info.`,
            vscode.DiagnosticSeverity.Error
          )
        );
      }
    }

    // Warn if apiVersion is not the expected value
    const apiMatch = trimmed.match(/^apiVersion:\s+(\S+)/);
    if (apiMatch && apiMatch[1] !== "aegis.dev/v1") {
      const col = line.indexOf(apiMatch[1]);
      const range = new vscode.Range(i, col, i, col + apiMatch[1].length);
      diagnostics.push(
        new vscode.Diagnostic(
          range,
          `Expected apiVersion 'aegis.dev/v1', got '${apiMatch[1]}'.`,
          vscode.DiagnosticSeverity.Warning
        )
      );
    }
  }

  diagnosticCollection.set(doc.uri, diagnostics);

  if (diagnostics.length === 0) {
    vscode.window.showInformationMessage("Aegis DQ: No issues found.");
  } else {
    vscode.window.showWarningMessage(
      `Aegis DQ: Found ${diagnostics.length} issue(s). See Problems panel.`
    );
  }
}

// ---------------------------------------------------------------------------
// Activate / Deactivate
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
  const diagnosticCollection =
    vscode.languages.createDiagnosticCollection("thota-dq");
  context.subscriptions.push(diagnosticCollection);

  // Hover provider for both the dedicated language and plain YAML
  const hoverProvider = buildHoverProvider();
  context.subscriptions.push(
    vscode.languages.registerHoverProvider("thota-rules", hoverProvider),
    vscode.languages.registerHoverProvider("yaml", hoverProvider)
  );

  // Validate command
  context.subscriptions.push(
    vscode.commands.registerCommand("aegisDQ.validateFile", () =>
      validateCurrentFile(diagnosticCollection)
    )
  );

  // Validate on save (when enabled)
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const config = vscode.workspace.getConfiguration("aegisDQ");
      if (!config.get<boolean>("validateOnSave", true)) return;

      const isRulesFile =
        doc.languageId === "thota-rules" ||
        doc.fileName.endsWith(".thota-dq.yaml") ||
        doc.fileName.endsWith(".thota-dq.yml") ||
        doc.fileName.endsWith("rules.yaml") ||
        doc.fileName.endsWith("rules.yml");

      if (isRulesFile) {
        validateCurrentFile(diagnosticCollection);
      }
    })
  );
}

export function deactivate(): void {
  // nothing to tear down
}
