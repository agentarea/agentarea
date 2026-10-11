/**
 * Lay valid JSON out one value per line, however it was written.
 *
 * A machine writes JSON on one line, and a file of it reads as a single
 * clipped row. Re-serialising through `JSON.parse` would also rewrite what the
 * file says — a 64-bit id loses its last digits — so this only moves the
 * whitespace between tokens and keeps every token as written. Text that is
 * not JSON comes back untouched.
 */
export function indentJson(text: string, indent = "  "): string {
  try {
    JSON.parse(text);
  } catch {
    return text;
  }

  let out = "";
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      out += ch;
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === " " || ch === "\n" || ch === "\r" || ch === "\t") continue;

    switch (ch) {
      case '"':
        inString = true;
        out += ch;
        break;
      case "{":
      case "[": {
        // An empty container stays on its line: `{}`, not a brace pair apart.
        let next = i + 1;
        while (next < text.length && /\s/.test(text[next])) next++;
        if (text[next] === (ch === "{" ? "}" : "]")) {
          out += ch + text[next];
          i = next;
          break;
        }
        depth++;
        out += ch + "\n" + indent.repeat(depth);
        break;
      }
      case "}":
      case "]":
        depth--;
        out += "\n" + indent.repeat(depth) + ch;
        break;
      case ",":
        out += ",\n" + indent.repeat(depth);
        break;
      case ":":
        out += ": ";
        break;
      default:
        out += ch;
    }
  }
  return out;
}
