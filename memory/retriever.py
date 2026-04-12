import math
import re
from datetime import datetime, timezone
from typing import Any


class MemoryRetriever:
    @staticmethod
    def tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
        return [token for token in tokens if len(token) > 1 or ("\u4e00" <= token <= "\u9fff")]

    @staticmethod
    def hash_vector(text: str, dim: int = 64) -> list[float]:
        tokens = MemoryRetriever.tokenize(text)
        vector = [0.0] * dim
        for token in tokens:
            hashed = hash(token)
            for index in range(dim):
                bit = (hashed >> (index % 62)) & 1
                vector[index] += 1.0 if bit else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @staticmethod
    def vector_cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    @staticmethod
    def jaccard_similarity(left: list[str], right: list[str]) -> float:
        left_set, right_set = set(left), set(right)
        union = len(left_set | right_set)
        if not union:
            return 0.0
        return len(left_set & right_set) / union

    def keyword_search(self, query: str, chunks: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []
        chunk_tokens = [self.tokenize(chunk["text"]) for chunk in chunks]
        document_count = len(chunks)
        document_frequency: dict[str, int] = {}
        for tokens in chunk_tokens:
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1

        def tfidf(tokens: list[str]) -> dict[str, float]:
            term_frequency: dict[str, int] = {}
            for token in tokens:
                term_frequency[token] = term_frequency.get(token, 0) + 1
            return {
                token: count * (math.log((document_count + 1) / (document_frequency.get(token, 0) + 1)) + 1)
                for token, count in term_frequency.items()
            }

        def cosine(left: dict[str, float], right: dict[str, float]) -> float:
            common = set(left) & set(right)
            if not common:
                return 0.0
            dot = sum(left[token] * right[token] for token in common)
            left_norm = math.sqrt(sum(value * value for value in left.values()))
            right_norm = math.sqrt(sum(value * value for value in right.values()))
            return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

        query_vector = tfidf(query_tokens)
        scored = []
        for index, tokens in enumerate(chunk_tokens):
            if not tokens:
                continue
            score = cosine(query_vector, tfidf(tokens))
            if score > 0.0:
                scored.append({"chunk": chunks[index], "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def vector_search(self, query: str, chunks: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
        query_vector = self.hash_vector(query)
        scored = []
        for chunk in chunks:
            score = self.vector_cosine(query_vector, self.hash_vector(chunk["text"]))
            if score > 0.0:
                scored.append({"chunk": chunk, "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def merge_results(
        self,
        vector_results: list[dict[str, Any]],
        keyword_results: list[dict[str, Any]],
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for item in vector_results:
            key = item["chunk"]["text"][:100]
            merged[key] = {"chunk": item["chunk"], "score": item["score"] * vector_weight}
        for item in keyword_results:
            key = item["chunk"]["text"][:100]
            if key in merged:
                merged[key]["score"] += item["score"] * keyword_weight
            else:
                merged[key] = {"chunk": item["chunk"], "score": item["score"] * keyword_weight}
        ranked = list(merged.values())
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    def apply_temporal_decay(self, ranked: list[dict[str, Any]], decay_rate: float = 0.01) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        for item in ranked:
            path = item["chunk"].get("path", "")
            age_days = 0.0
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", path)
            if date_match:
                try:
                    chunk_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    age_days = (now - chunk_date).total_seconds() / 86400.0
                except ValueError:
                    pass
            item["score"] *= math.exp(-decay_rate * age_days)
        return ranked

    def mmr_rerank(self, ranked: list[dict[str, Any]], lambda_param: float = 0.7) -> list[dict[str, Any]]:
        if len(ranked) <= 1:
            return ranked
        tokenized = [self.tokenize(item["chunk"]["text"]) for item in ranked]
        selected: list[int] = []
        remaining = list(range(len(ranked)))
        result: list[dict[str, Any]] = []
        while remaining:
            best_index = -1
            best_score = float("-inf")
            for index in remaining:
                relevance = ranked[index]["score"]
                diversity_penalty = 0.0
                for selected_index in selected:
                    similarity = self.jaccard_similarity(tokenized[index], tokenized[selected_index])
                    if similarity > diversity_penalty:
                        diversity_penalty = similarity
                mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity_penalty
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_index = index
            selected.append(best_index)
            remaining.remove(best_index)
            result.append(ranked[best_index])
        return result

    def rank(self, query: str, chunks: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
        if not chunks:
            return []
        keyword_results = self.keyword_search(query, chunks, top_k=10)
        vector_results = self.vector_search(query, chunks, top_k=10)
        merged = self.merge_results(vector_results, keyword_results)
        decayed = self.apply_temporal_decay(merged)
        return self.mmr_rerank(decayed)[:top_k]
