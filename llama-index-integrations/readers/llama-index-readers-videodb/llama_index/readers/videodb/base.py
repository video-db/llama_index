from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import (
    BaseNode,
    TextNode,
    Document,
)

from llama_index.core.bridge.pydantic import Field

import logging
import os

from typing import Optional, List
from videodb import connect, SearchType, IndexType


logger = logging.getLogger(__name__)


class VideoDocument(Document):
    worded_transcript: Optional[List] = Field(
        default_factory=None,
        description="Unique ID of the node.",
    )


class VideoDBReader(BaseReader):
    def __init__(
        self,
        api_key: Optional[str] = None,
        collection: Optional[str] = "default",
        video: Optional[str] = None,
        base_url: Optional[str] = None,
        index_id: Optional[str] = None,
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
        self.video = video
        self.collection = collection
        self.index_id = index_id

    # TODO: setter/getter ?
    def _conn(self):
        kwargs = {"api_key": self._api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        conn = connect(**kwargs)
        return conn

    def load_data(
        self,
        video_ids: Optional[List[str]] = None,
        collection_ids: Optional[List[str]] = None,
    ) -> List[Document]:

        conn = self._conn()
        coll = conn.get_collection(self.collection)

        if video_ids is None and collection_ids is None:
            raise ValueError("Either video_ids or collection_ids is required.")

        documents = []
        if video_ids:
            for video_id in video_ids:
                video = coll.get_video(video_id)
                worded_transcript = video.get_transcript()
                transcript_text = video.get_transcript_text()
                # TODO: worded transcript cannot go into metadata, it should be seperate field, Check what should be the correct one ?
                document = VideoDocument(
                    text=transcript_text,
                    metadata={
                        "type": "transcript",
                        "video_id": video_id,
                    },
                )
                document.worded_transcript = worded_transcript
                documents.append(document)

        if collection_ids:
            raise NotImplementedError(
                "Loading data based on collection_ids is not implemented yet."
            )

        return documents

    def post_process_transcript_nodes(
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
                chunk = chunk.replace("-", "").strip(" ")
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
                update = {"video_start": start, "video_end": end, "shots": len(shots)}
                node.metadata.update(update)

    # def get_transcript_nodes(self, window=90, overlap=0):
    #     # TODO: take timeline also
    #     conn = self._conn()
    #     nodes = []
    #     coll = conn.get_collection(self.collection)
    #     video = coll.get_video(self.video)
    #     transcript = video.get_transcript()

    #     initial_start = 0
    #     processed_count = 0  # to track if end of window is reached
    #     last_full_stop_start = 0
    #     last_full_stop_end = 0
    #     input_text = ""
    #     len_of_transcript = len(transcript)
    #     for i, transcript_block in enumerate(transcript):
    #         if "word" in transcript_block:
    #             transcript_block["text"] = transcript_block.get("word")  # TEMP
    #         transcript_block_text = transcript_block.get("text")
    #         start = float(
    #             transcript_block.get("start")
    #         )  # since Decimal is used in Dynamo
    #         end = float(transcript_block.get("end"))
    #         if i == 0:
    #             if transcript_block_text != "-":
    #                 input_text += f"{transcript_block_text}"
    #         else:
    #             if transcript_block_text != "-":
    #                 input_text += f" {transcript_block_text}"
    #         if "." in transcript_block_text:
    #             last_full_stop_start = start
    #             last_full_stop_end = end
    #         if (end // window > processed_count) or (i == len_of_transcript - 1):
    #             # if chunk of window or remaning text at end
    #             # input_text = stiched text for window size, incomplete sentence carried forward from last iteration
    #             # strategy conservative, shave extra incomplete sentence
    #             processed_count += 1
    #             if "." in input_text:
    #                 full_stop_position = input_text.rindex(".") + 1
    #                 complete_paragraph = input_text[:full_stop_position]
    #                 incomplete_paragraph = input_text[full_stop_position:]
    #             else:
    #                 # no '.' found in chunk
    #                 complete_paragraph = input_text
    #                 incomplete_paragraph = ""
    #                 last_full_stop_start = end
    #                 last_full_stop_end = end
    #             transcript_block_dict = {}
    #             transcript_block_dict["start"] = initial_start
    #             transcript_block_dict["end"] = last_full_stop_end
    #             transcript_block_dict["text"] = complete_paragraph
    #             if i == len_of_transcript - 1:
    #                 # i.e incomplete_paragraph will be stuck
    #                 transcript_block_dict["text"] += f"{incomplete_paragraph}"
    #                 transcript_block_dict["end"] = end
    #             nodes.append(
    #                 TextNode(
    #                     text=transcript_block_dict["text"],
    #                     metadata={
    #                         "type": "spoken",
    #                         "start": transcript_block_dict["start"],
    #                         "end": transcript_block_dict["end"],
    #                     },
    #                 )
    #             )
    #             input_text = incomplete_paragraph
    #             initial_start = last_full_stop_start
    #     return nodes

    # def get_scene_nodes(self, scn_col_id: Optional[str] = None):
    #     kwargs = {"api_key": self._api_key}
    #     if self._base_url is not None:
    #         kwargs["base_url"] = self._base_url
    #     conn = connect(**kwargs)

    #     nodes = []
    #     if scn_col_id:
    #         coll = conn.get_collection(self.collection)
    #         video = coll.get_video(self.video)
    #         scn_col = video.get_scene_collection(scn_col_id)
    #         for scene in scn_col.scenes:
    #             if scene.description is None:
    #                 # TODO: throw an error
    #                 continue
    #             else:
    #                 textnode = TextNode(
    #                     text=scene.description,
    #                     # TODO: add frames
    #                     metadata={
    #                         "type": "scene",
    #                         "id": scene.id,
    #                         "video_id": scene.video_id,
    #                         "start": scene.start,
    #                         "end": scene.end,
    #                         "start": scene.start,
    #                         "end": scene.end,
    #                     },
    #                 )
    #                 nodes.append(textnode)
    #     return nodes


def post(nodes: List[BaseNode], docs: List[Document]) -> List[BaseNode]:
    for i, node in enumerate(nodes):
        for doc in docs:
            if doc.id_ == node.ref_doc_id:
                parent_doc = doc

        if parent_doc is not None:
            chunk = node.text
            detailed_transcript = parent_doc.worded_transcript
            chunk_words = chunk.split()
            chunk_length = len(chunk_words)
            start = None
            end = None

            for i in range(len(detailed_transcript) - chunk_length + 1):
                match = True
                for j in range(chunk_length):
                    if detailed_transcript[i + j]["text"] != chunk_words[j]:
                        match = False
                        break
                if match:
                    start = detailed_transcript[i]["start"]
                    end = detailed_transcript[i + chunk_length - 1]["end"]

            updated = {"video_start": start, "video_end": end}
            node.metadata.update(updated)

        # # establish prev/next relationships if nodes share the same source_node
        # if (
        #     i > 0
        #     and node.source_node
        #     and nodes[i - 1].source_node
        #     and nodes[i - 1].source_node.node_id == node.source_node.node_id
        # ):
        #     node.relationships[NodeRelationship.PREVIOUS] = nodes[
        #         i - 1
        #     ].as_related_node_info()
        # if (
        #     i < len(nodes) - 1
        #     and node.source_node
        #     and nodes[i + 1].source_node
        #     and nodes[i + 1].source_node.node_id == node.source_node.node_id
        # ):
        #     node.relationships[NodeRelationship.NEXT] = nodes[
        #         i + 1
        #     ].as_related_node_info()

    return nodes
