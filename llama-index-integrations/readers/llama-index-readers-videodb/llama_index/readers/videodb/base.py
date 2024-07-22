from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import (
    TextNode,
    Document,
)

from llama_index.core.bridge.pydantic import Field

import logging
import os
import re


from typing import Optional, List
from videodb import connect, SearchType, IndexType


logger = logging.getLogger(__name__)


def find_substring_by_word(main_string, substring):
    substring = re.escape(substring)
    # Split the main string into words
    words = main_string.split()

    # Join words into a string to find the exact match for the substring
    joined_string = " ".join(words)
    matched_results = [
        (match.span(), match.group())
        for match in re.finditer(substring, joined_string, re.IGNORECASE)
    ]
    words_positions = []
    matched_strings = []
    scores = []

    for (start_index, end_index), text in matched_results:
        # Count words before the substring to find its starting word position
        start_word_count = joined_string[:start_index].count(" ")
        end_word_count = joined_string[:end_index].count(" ")
        words_position = (start_word_count, end_word_count)
        words_positions.append(words_position)
        matched_strings.append(text)
        scores.append(1)
    return words_positions, matched_strings, scores


# Should be used in case client keyword search is required
class VideoDocument(Document):
    transcript_without_silence: Optional[List] = Field(
        default_factory=None,
        description="Unique ID of the node.",
    )

    transcript_text: Optional[str] = Field(
        default_factory=None, description="Transcript Text"
    )


class VideoDBReader(BaseReader):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """Creates a new VideoDB Retriever."""
        if api_key is None:
            api_key = os.environ.get("VIDEO_DB_API_KEY")
        if api_key is None:
            raise Exception(
                "No API key provided. Set an API key either as an environment variable (VIDEO_DB_API_KEY) or pass it as an argument."
            )
        self._api_key = api_key
        self._base_url = base_url

    # TODO: setter/getter ?
    def _conn(self):
        kwargs = {"api_key": self._api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        conn = connect(**kwargs)
        return conn

    def load_data(
        self,
        video_id: Optional[str] = None,
        coll_id: Optional[str] = "default",
        load_transcript: Optional[bool] = False,
        load_scene: Optional[bool] = False,
        scn_col_id: Optional[str] = None,
    ) -> List[Document]:

        conn = self._conn()
        coll = conn.get_collection(coll_id)

        if video_id is None:
            raise ValueError("video_id is required.")

        if not (load_transcript and load_scene):
            raise ValueError("Either load_scene or load_transcript is required.")

        documents = []
        if load_transcript:
            video = coll.get_video(video_id)
            transcript = video.get_transcript()
            transcript_without_silence = []
            transcript_text = ""
            for word in transcript:
                text = word.get("text")
                if text != "-":
                    transcript_text += text
                    transcript_without_silence.append(word)
                    transcript_text += " "

            document = VideoDocument(
                text=transcript_text,
                metadata={
                    "type": "transcript",
                    "video_id": video_id,
                },
            )
            document.transcript_text = transcript_text
            document.transcript_without_silence = transcript_without_silence
            documents.append(document)
        if load_scene:
            video = coll.get_video(video_id)
            scn_col = video.get_scene_collection(scn_col_id)
            # TODO: Support for frame description
            for scene in scn_col.scenes:
                if scene.description is not None:
                    document = VideoDocument(
                        text=scene.description,
                        metadata={
                            "type": "scene",
                            "scene_start": scene.start,
                            "scene_end": scene.end,
                        },
                    )
                    documents.append(document)
        return documents

    def post_process_transcript_nodes(
        self, nodes: List[TextNode], docs: List[Document]
    ) -> List[TextNode]:
        for node in nodes:
            for doc in docs:
                if doc.id_ == node.ref_doc_id:
                    parent_doc = doc

            if (parent_doc is not None) and (
                parent_doc.metadata["type"] == "transcript"
            ):
                chunk = node.text
                transcript_text = parent_doc.transcript_text
                transcript_without_silence = parent_doc.transcript_without_silence
                start = None
                end = None

                word_positions, matched_strings, scores = find_substring_by_word(
                    transcript_text, chunk
                )

                if word_positions:
                    # TODO: edge case, if a chunk has appeared twice, select correct chunk
                    word_position = word_positions[0]

                    start_word = transcript_without_silence[word_position[0]]
                    end_word = transcript_without_silence[word_position[-1]]
                    start = start_word.get("start")
                    end = end_word.get("start")

                node.metadata.update({"video_start": start, "video_end": end})

            if (parent_doc is not None) and (parent_doc.metadata["type"] == "scene"):
                start = parent_doc.metadata["scene_start"]
                end = parent_doc.metadata["scene_end"]
                node.metadata.update({"video_start": start, "video_end": end})

    def post_process_transcript_nodes_old(
        self, nodes: List[TextNode], docs: List[Document]
    ) -> List[TextNode]:
        conn = self._conn()
        for i, node in enumerate(nodes):
            for doc in docs:
                if doc.id_ == node.ref_doc_id:
                    parent_doc = doc

            coll = conn.get_collection(self.collection)
            video = coll.get_video(parent_doc.metadata["video_id"])

            if parent_doc is not None:
                chunk = node.text
                chunk = chunk.replace(" - ", " ").replace("-", "").strip(" ")
                start = None
                end = None

                res = video.search(
                    chunk,
                    search_type=SearchType.keyword,
                    index_type=IndexType.spoken_word,
                )
                shots = res.shots
                if shots:
                    start = shots[0].start
                    end = shots[0].end
                update = {
                    "video_start_old": start,
                    "video_end_old": end,
                    "shots": len(shots),
                }
                node.metadata.update(update)
