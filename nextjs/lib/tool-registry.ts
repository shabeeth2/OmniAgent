export type QueryProperty = { type: "string" | "number" | "integer" | "boolean"; description?: string };
export type QuerySchema = { type: "object"; properties: Record<string, QueryProperty>; required: string[]; additionalProperties: false };
export type RegistryTool = { name: string; description: string; input_schema: Record<string, unknown> };
export type ToolEffect = "read" | "write" | "unknown";
export type RegistryEntry = {
  id: string; name: string; kind: "mcp" | "api"; url: string; description: string;
  auth_scheme: "none" | "bearer" | "api_key"; auth_header: string; has_api_key: boolean;
  method: string; input_schema: QuerySchema; status: "saved" | "passed" | "failed";
  tested_at: string | null; error: string | null; tools: RegistryTool[]; enabled_tools: string[];
  tool_effects?: Record<string, ToolEffect>;
};
export const emptySchema: QuerySchema = { type: "object", properties: {}, required: [], additionalProperties: false };

export function parseQuerySchema(text: string): QuerySchema {
  let value;
  try { value = JSON.parse(text); } catch { throw new Error("Input schema must be valid JSON."); }
  if (!value || value.type !== "object" || !value.properties || Array.isArray(value.properties) || typeof value.properties !== "object") throw new Error("Use an object schema with a properties object.");
  for (const [name, property] of Object.entries(value.properties)) {
    const item = property as QueryProperty;
    if (!name.trim() || !item || !["string", "number", "integer", "boolean"].includes(item.type)) throw new Error("Query parameters must use string, number, integer, or boolean types.");
    if (Object.keys(item).some(key => !["type", "description"].includes(key))) throw new Error("Query properties support type and description only.");
    if (item.description !== undefined && typeof item.description !== "string") throw new Error("Parameter descriptions must be text.");
  }
  const required = value.required ?? [];
  if (!Array.isArray(required) || required.some((name: unknown) => typeof name !== "string" || !Object.hasOwn(value.properties, name))) throw new Error("Required parameters must name declared properties.");
  if (Object.keys(value).some(key => !["type", "properties", "required", "additionalProperties"].includes(key)) || (value.additionalProperties !== undefined && value.additionalProperties !== false)) throw new Error("Use only type, properties, required, and additionalProperties: false.");
  return { type: "object", properties: value.properties, required, additionalProperties: false };
}

export function parseTestArguments(schema: QuerySchema, values: Record<string, string>): Record<string, string | number | boolean> {
  const result: Record<string, string | number | boolean> = Object.create(null);
  for (const [name, property] of Object.entries(schema.properties)) {
    const value = Object.hasOwn(values, name) ? values[name] : "";
    if (value === "") {
      if (schema.required.includes(name)) throw new Error(`Enter a value for ${name}.`);
      continue;
    }
    if (property.type === "string") result[name] = value;
    else if (property.type === "boolean") {
      if (!["true", "false"].includes(value)) throw new Error(`${name} must be true or false.`);
      result[name] = value === "true";
    } else {
      const number = Number(value);
      if (!value.trim() || !Number.isFinite(number) || (property.type === "integer" && !Number.isInteger(number))) throw new Error(`${name} must be a valid ${property.type}.`);
      result[name] = number;
    }
  }
  return result;
}
