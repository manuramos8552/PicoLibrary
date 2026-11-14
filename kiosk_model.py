"""
kiosk_model.py
Model for the Satisfaction Kiosk (Mini-Lab 3).
Pure logic - no hardware here, so it can be tested on its own.
"""


class FeedbackStats:
    """Keeps track of positive / negative feedback and the satisfaction rate."""

    def __init__(self, threshold=30, min_votes=5):
        self._positive = 0
        self._negative = 0
        self._threshold = threshold      # alarm when satisfaction % falls below this
        self._min_votes = min_votes      # don't alarm until we have enough votes

    def add_positive(self):
        self._positive += 1

    def add_negative(self):
        self._negative += 1

    def reset(self):
        self._positive = 0
        self._negative = 0

    def total(self):
        return self._positive + self._negative

    def positive(self):
        return self._positive

    def negative(self):
        return self._negative

    def satisfaction(self):
        """Percentage of positive feedback (100 if no votes yet)."""
        if self.total() == 0:
            return 100
        return round(self._positive * 100 / self.total())

    def is_below_threshold(self):
        return self.total() >= self._min_votes and self.satisfaction() < self._threshold

    def __str__(self):
        return "+{} -{} {}%".format(self._positive, self._negative, self.satisfaction())
