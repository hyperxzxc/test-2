import pytest

from app.domain import rebalance, stream_fingerprint
from app.errors import AppError
from app.schemas import OfferBinding


def test_remainder_is_deterministic_and_sums_to_100():
    result = rebalance([OfferBinding(offer_id=i, share=0) for i in (1, 2, 3)])
    assert [b.share for b in result] == [33, 33, 34]


def test_video_pinned_example():
    result = rebalance(
        [
            OfferBinding(offer_id=1, share=25, pinned=True),
            OfferBinding(offer_id=2, share=25),
            OfferBinding(offer_id=3, share=0),
            OfferBinding(offer_id=4, share=90, removed=True),
        ]
    )
    assert [b.share for b in result] == [25, 37, 38, 0]


@pytest.mark.parametrize(
    "bindings",
    [
        [],
        [OfferBinding(offer_id=1, share=0, removed=True)],
        [
            OfferBinding(offer_id=1, share=70, pinned=True),
            OfferBinding(offer_id=2, share=40, pinned=True),
        ],
        [OfferBinding(offer_id=1, share=25, pinned=True)],
    ],
)
def test_invalid_distributions_are_rejected(bindings):
    with pytest.raises(AppError):
        rebalance(bindings)


def test_many_offer_counts_and_pinned_values():
    for pinned in range(0, 101):
        for count in range(1, 15):
            original = [OfferBinding(offer_id=1, share=pinned, pinned=True)] + [
                OfferBinding(offer_id=i + 2, share=0) for i in range(count)
            ]
            result = rebalance(original)
            assert result[0].share == pinned
            assert sum(b.share for b in result) == 100
            assert max(b.share for b in result[1:]) - min(b.share for b in result[1:]) <= 1
            assert original[-1].share == 0


def test_keitaro_normalization_is_not_an_external_conflict():
    stream = {
        "id": 1,
        "schema": "landings",
        "action_payload": None,
        "offers": [{"offer_id": 1, "share": 100, "state": "active"}],
    }
    normalized = {**stream, "action_payload": ""}
    assert stream_fingerprint(stream) == stream_fingerprint(normalized)
    changed = {**stream, "filters": [{"name": "country", "payload": ["AU"]}]}
    assert stream_fingerprint(stream) != stream_fingerprint(changed)
