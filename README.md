# blinkit-mcp

A local, read-only MCP server for browsing [Blinkit](https://blinkit.com) at
your delivery address. An assistant can search products, read prices and
stock, get full product details, and look at product images (for example, to
read a nutrition table on the back of a pack).

It does not log in, use a cart, or place orders.

> **Warning:** Blinkit has no public API. This server uses the private API of
> the blinkit.com web app. Blinkit can change or block it at any time. Use it
> for personal use only, at low request rates.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)

## Install

```sh
git clone <this repo> blinkit-mcp
cd blinkit-mcp
uv sync
```

## Register the server

**Claude Code:**

```sh
claude mcp add blinkit -- uv --directory /absolute/path/to/blinkit-mcp run blinkit-mcp
```

**Claude Desktop:** add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "blinkit": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/blinkit-mcp", "run", "blinkit-mcp"]
    }
  }
}
```

## Tools

| Tool | What it does |
|------|--------------|
| `set_location` | Saves the delivery location. Give an `address` to get candidate places, then call again with the chosen `place_id`. You can also give `lat` and `lon`. It checks that Blinkit delivers there. |
| `get_location` | Returns the saved location. |
| `search_products` | Searches one item. Returns `status` (`found`, `all_sold_out`, `no_match`) and products with price, MRP, pack size, stock, image URL, and `product_id`. It removes unrelated sponsored items. |
| `get_product` | Returns all gallery image URLs and all customer-visible attributes: description, ingredients, shelf life, manufacturer, FSSAI licence, and often nutrition per 100 g. |
| `view_images` | Returns product images (up to 4 per call, long side at most 1500 px) so the assistant can read them. |

All tools except `view_images` with `urls` use the saved location. You can
override it for one call with `lat` and `lon`.

Errors come back as `{"status": "<code>", "message": "..."}`. The codes are:
`no_location`, `blocked`, `not_serviceable`, `not_found`, `upstream_changed`,
`network`, `bad_input`.

## Configuration

The location is saved in `~/.config/blinkit-mcp/config.json`. To use a
different file, set `BLINKIT_MCP_CONFIG`.

## Development

```sh
uv run pytest                                # unit tests (saved responses)
BLINKIT_LIVE=1 uv run pytest tests/test_live.py   # end-to-end against blinkit.com
uv run python scripts/capture_fixtures.py    # refresh saved responses
```

All knowledge of Blinkit's response formats is in `src/blinkit_mcp/parsers.py`.
If Blinkit changes its API, fix it there. The design notes are in
`docs/superpowers/specs/`.
