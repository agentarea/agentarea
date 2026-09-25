import fs from "node:fs/promises";
import path from "node:path";

export type DatasetSnapshot = {
  dataset: string;
  columns: string[];
  rows: Record<string, string>[];
};

const UNSUPPORTED_VALUE = /[",\r\n]/;

/**
 * A CSV file bound to the app from outside.
 *
 * The app never names its data: the server receives the binding at start, so
 * the same view can be pointed at any dataset that has the columns it needs,
 * and replacing the view never touches the data.
 */
export class CsvDataset {
  #writes: Promise<unknown> = Promise.resolve();

  constructor(
    readonly filePath: string,
    readonly requiredColumns: readonly string[],
  ) {}

  async read(): Promise<DatasetSnapshot> {
    const text = await fs.readFile(this.filePath, "utf-8");
    const [headerLine, ...lines] = text.split(/\r?\n/).filter((line) => line.length > 0);
    if (headerLine === undefined) {
      throw new Error(`${this.filePath}: dataset has no header row`);
    }

    const columns = this.#fields(headerLine, 1);
    const missing = this.requiredColumns.filter((column) => !columns.includes(column));
    if (missing.length > 0) {
      throw new Error(`${this.filePath}: dataset lacks columns the app needs: ${missing.join(", ")}`);
    }

    const rows = lines.map((line, index) => {
      const fields = this.#fields(line, index + 2);
      if (fields.length !== columns.length) {
        throw new Error(
          `${this.filePath}:${index + 2}: expected ${columns.length} fields, found ${fields.length}`,
        );
      }
      return Object.fromEntries(columns.map((column, i) => [column, fields[i]]));
    });

    return { dataset: path.basename(this.filePath), columns, rows };
  }

  /** Serialized so two concurrent actions cannot interleave a read and a write. */
  updateCell(id: string, column: string, value: string): Promise<DatasetSnapshot> {
    const update = this.#writes.then(async () => {
      if (UNSUPPORTED_VALUE.test(value)) {
        throw new Error(`value for ${column} contains a comma, quote, or line break`);
      }
      const snapshot = await this.read();
      if (!snapshot.columns.includes(column)) {
        throw new Error(`dataset has no column ${column}`);
      }
      const row = snapshot.rows.find((candidate) => candidate.id === id);
      if (!row) {
        throw new Error(`dataset has no row with id ${id}`);
      }
      row[column] = value;

      const lines = [
        snapshot.columns.join(","),
        ...snapshot.rows.map((r) => snapshot.columns.map((c) => r[c]).join(",")),
      ];
      await fs.writeFile(this.filePath, `${lines.join("\n")}\n`, "utf-8");
      return snapshot;
    });
    this.#writes = update.catch(() => undefined);
    return update;
  }

  #fields(line: string, lineNumber: number): string[] {
    if (line.includes('"')) {
      throw new Error(`${this.filePath}:${lineNumber}: quoted CSV fields are not supported`);
    }
    return line.split(",");
  }
}
