import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.services.sentiment_analyzer import analyzer
from app.services.scoring_engine import scoring_engine

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

def test_api_key_unauthorized():
    response = client.post("/api/v1/jobs/fetch-creator", json={
        "platform": "IG",
        "handle": "test_creator"
    })
    assert response.status_code == 401

def test_sentiment_analyzer_pidgin_boost():
    # Test positive Pidgin phrase boost
    res = analyzer.analyze_comment("This creator content dey sweet die! Really good.")
    assert res["sentiment"] == "POSITIVE"
    assert res["score"] > 0.3

    # Test negative Pidgin phrase
    res_neg = analyzer.analyze_comment("Pure scam, this brand fall my hand totally.")
    assert res_neg["sentiment"] == "NEGATIVE"
    assert res_neg["score"] < -0.2

def test_scoring_engine():
    sample_metrics = [{
        "followers": 50000,
        "engagement_rate": 0.035,
        "avg_likes": 1700,
        "avg_comments": 80
    }]
    score_res = scoring_engine.calculate_centi_score(sample_metrics)
    assert "centi_score" in score_res
    assert 10 <= score_res["centi_score"] <= 99
    assert score_res["grade"] in ["A+", "A", "B", "C", "D"]
    assert "components" in score_res
