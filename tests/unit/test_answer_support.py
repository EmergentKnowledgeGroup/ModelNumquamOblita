from engine.contracts import MemoryPack, MemoryPackItem, SourceRef
from engine.retrieval.answer_support import check_answer_claims


def _pack(text="We are not launching on Friday.", **overrides):
    item = MemoryPackItem(atom_id="launch", canonical_text=text, confidence=0.9,
                          source_refs=[SourceRef(source_id="launch_source", message_id="m1")], **overrides)
    return MemoryPack(core=[item])


def test_relevant_words_do_not_verify_an_answer():
    result = check_answer_claims(["We are launching on Friday.", "We are launching on Monday."], _pack())
    assert result["status"] == "UNVERIFIED"
    assert all(not check["supported"] for check in result["checks"])
    assert all(check["citations"] == [] for check in result["checks"])


def test_exact_memory_wording_retains_its_own_source():
    result = check_answer_claims(["We are not launching on Friday."], _pack())
    assert result["status"] == "SUPPORTED"
    assert result["checks"][0]["citations"] == ["launch_source#m1"]
    assert result["checks"][0]["evidence_id"] == "launch"


def test_conflict_and_continuity_cannot_supply_answer_support():
    pack = _pack()
    item = pack.core.pop()
    pack.conflict.append(item)
    pack.continuity.append(item)
    assert check_answer_claims([item.canonical_text], pack)["status"] == "UNVERIFIED"
    assert check_answer_claims([item.canonical_text], _pack(conflict_state="superseded"))["status"] == "UNVERIFIED"


def test_an_independent_matching_item_can_support_without_combining_sources():
    pack = _pack()
    matching = _pack("We are launching on Friday.").core[0]
    matching.atom_id = "current_launch"
    matching.source_refs = [SourceRef(source_id="current_source", message_id="m2")]
    pack.core.append(matching)
    result = check_answer_claims([matching.canonical_text], pack)
    assert result["checks"][0]["citations"] == ["current_source#m2"]


def test_empty_claims_are_not_checked():
    assert check_answer_claims(None, _pack()) == {"status": "NOT_CHECKED", "checks": []}


def test_short_term_helper_text_cannot_certify_an_answer():
    pack = _pack(memory_layer="short_term", trust_tier="ephemeral")
    assert check_answer_claims([pack.core[0].canonical_text], pack)["status"] == "UNVERIFIED"
