# ScienceClaw Browser-use Compatibility Distribution

This source distribution is derived from `browser-use/browser-use` under the
MIT License. The upstream source baseline is commit
`2454d3e2551705232333c906ded8fc31ab0fc9f2` (`0.13.2`).

ScienceClaw package version: `0.13.2+sciclaw.1`.

Changes from the upstream packaging metadata:

- Keep the Browser-use core plus the OpenAI and Anthropic wrappers required by
  the co-resident legacy RPA route.
- Move CLI, MCP, Google, Groq, Ollama and Skills SDK dependencies to opt-in
  extras so they do not expand the RPA Agent Next runtime image.
- Align the Anthropic SDK to `0.96.0`, which is compatible with the pinned
  `langchain-anthropic==1.4.6` baseline. Import and construction compatibility
  has been probed; real Anthropic calls are not an F032 capability claim.

F032 itself only exposes OpenAI-compatible models. The package retains the
Anthropic wrapper solely to avoid changing the independently supported legacy
RPA route in the same backend process.
