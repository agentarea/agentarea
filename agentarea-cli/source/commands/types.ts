// Declarative command registry types. Each CommandSpec maps a human-facing
// `<noun> <verb>` to a generated SDK function, describing how CLI positional
// args and flags become the SDK call's path/query/body. The router
// (commands/router.ts) is generic over these specs; adding a command is a
// data change, not new dispatch code.

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export interface CommandSpec {
	/** Resource group, e.g. "agents", "policies", "access". */
	noun: string;
	/** Action, e.g. "list", "get", "create". */
	verb: string;
	/** Alternate verbs that resolve to this spec (e.g. "rm" -> "delete"). */
	aliases?: string[];
	/** SDK export name from @agentarea/api-client. */
	fn: string;
	method: HttpMethod;
	/**
	 * Path parameter names, in the order positional CLI args fill them.
	 * e.g. tasks get <agentId> <taskId> -> ['agent_id', 'task_id'].
	 */
	pathParams: string[];
	/** Whether the operation accepts a request body. */
	body: boolean;
	/** One-line help text. */
	summary: string;
}
