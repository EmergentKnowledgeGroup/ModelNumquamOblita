from engine.mcp.server import AuthConfig, MCPServer, ServerConfig


def test_brief_keeps_the_source_of_its_selected_text(monkeypatch):
    server = MCPServer(config=ServerConfig(auth=AuthConfig(default_role="viewer")), api_client=object())
    monkeypatch.setattr(server, "_tool_explore_expand_anchor", lambda args: {
        "status": "supported", "anchor": {"label": "Launch"}, "connected_atoms": [{
            "summary": "Launch is not on Friday.", "source_ref": "launch_source#m1", "confidence": 0.9}],
        "next_hops": []})
    monkeypatch.setattr(server, "_tool_explore_peek", lambda args: {
        "snippets": [{"snippet": "Hahahah!", "source_ref": "other_source#m9", "confidence": 0.1}]})
    result = server._build_anchor_brief_payload(anchor_id="launch", anchor_type="project", limit=4)
    assert "not on Friday" in result["summary"]
    assert result["citation_refs"][0] == "launch_source#m1"
    assert result["summary_support"]["source_ref"] == "launch_source#m1"
    assert result["summary_support"]["confidence"] == 0.9
    assert result["summary_kind"] == "source_selection"
    assert result["summary_support"]["scope"] == "selected_source"
    assert result["confidence"] == 0.1  # Preserve the legacy aggregate field.


def test_brief_empty_support_stays_explicit(monkeypatch):
    server = MCPServer(config=ServerConfig(auth=AuthConfig(default_role="viewer")), api_client=object())
    monkeypatch.setattr(server, "_tool_explore_expand_anchor", lambda args: {"status": "insufficient_support"})
    monkeypatch.setattr(server, "_tool_explore_peek", lambda args: {"snippets": []})
    result = server._build_anchor_brief_payload(anchor_id="launch", anchor_type="project", limit=4)
    assert result["summary_support"] is None
    assert result["citation_refs"] == []
    assert "Insufficient support" in result["summary"]
