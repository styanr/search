from PyQt6.QtCore import QObject, pyqtSignal

from circlesearch.core.pipeline import Pipeline
from circlesearch.ui.cards import view_for


def prepared(card):
    return None if card is None else view_for(card).prepare(card)


class CardFeed(QObject):
    routed = pyqtSignal(int, object, bool)
    ready = pyqtSignal(int, object, object)
    extra = pyqtSignal(int, object, object)

    def __init__(self, parent=None, pipeline=None):
        super().__init__(parent)
        self.pipeline = pipeline or Pipeline()
        self.token = 0
        self.job = None

    def start(self, text):
        self.cancel()
        self.token += 1
        token = self.token
        self.job = self.pipeline.start(
            text,
            lambda route, placeholder: self.routed.emit(token, route, placeholder),
            lambda card: self.ready.emit(token, card, prepared(card)),
            lambda card: self.extra.emit(token, card, prepared(card)))
        return token

    def cancel(self):
        if self.job is not None:
            self.job.cancel()
            self.job = None
