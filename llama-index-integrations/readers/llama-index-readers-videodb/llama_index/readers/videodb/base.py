from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import TextNode

import logging
import os

from typing import Optional
from videodb import connect


logger = logging.getLogger(__name__)


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

    def get_transcript_nodes(self, window=90, overlap=0):
        # TODO: take timeline also
        kwargs = {"api_key": self._api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        conn = connect(**kwargs)
        nodes = []
        coll = conn.get_collection(self.collection)
        video = coll.get_video(self.video)
        transcript = video.get_transcript()

        initial_start = 0
        processed_count = 0  # to track if end of window is reached
        last_full_stop_start = 0
        last_full_stop_end = 0
        input_text = ""
        len_of_transcript = len(transcript)
        for i, transcript_block in enumerate(transcript):
            if "word" in transcript_block:
                transcript_block["text"] = transcript_block.get("word")  # TEMP
            transcript_block_text = transcript_block.get("text")
            start = float(
                transcript_block.get("start")
            )  # since Decimal is used in Dynamo
            end = float(transcript_block.get("end"))
            if i == 0:
                if transcript_block_text != "-":
                    input_text += f"{transcript_block_text}"
            else:
                if transcript_block_text != "-":
                    input_text += f" {transcript_block_text}"
            if "." in transcript_block_text:
                last_full_stop_start = start
                last_full_stop_end = end
            if (end // window > processed_count) or (i == len_of_transcript - 1):
                # if chunk of window or remaning text at end
                # input_text = stiched text for window size, incomplete sentence carried forward from last iteration
                # strategy conservative, shave extra incomplete sentence
                processed_count += 1
                if "." in input_text:
                    full_stop_position = input_text.rindex(".") + 1
                    complete_paragraph = input_text[:full_stop_position]
                    incomplete_paragraph = input_text[full_stop_position:]
                else:
                    # no '.' found in chunk
                    complete_paragraph = input_text
                    incomplete_paragraph = ""
                    last_full_stop_start = end
                    last_full_stop_end = end
                transcript_block_dict = {}
                transcript_block_dict["start"] = initial_start
                transcript_block_dict["end"] = last_full_stop_end
                transcript_block_dict["text"] = complete_paragraph
                if i == len_of_transcript - 1:
                    # i.e incomplete_paragraph will be stuck
                    transcript_block_dict["text"] += f"{incomplete_paragraph}"
                    transcript_block_dict["end"] = end
                nodes.append(
                    TextNode(
                        text=transcript_block_dict["text"],
                        metadata={
                            "type": "spoken",
                            "start": transcript_block_dict["start"],
                            "end": transcript_block_dict["end"],
                        },
                    )
                )
                input_text = incomplete_paragraph
                initial_start = last_full_stop_start
        return nodes

    def get_scene_nodes(self, scn_col_id: Optional[str] = None):
        kwargs = {"api_key": self._api_key}
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        conn = connect(**kwargs)

        nodes = []
        if scn_col_id:
            coll = conn.get_collection(self.collection)
            video = coll.get_video(self.video)
            scn_col = video.get_scene_collection(scn_col_id)
            for scene in scn_col.scenes:
                if scene.description is None:
                    # TODO: throw an error
                    continue
                else:
                    textnode = TextNode(
                        text=scene.description,
                        # TODO: add frames
                        metadata={
                            "type": "scene",
                            "id": scene.id,
                            "video_id": scene.video_id,
                            "start": scene.start,
                            "end": scene.end,
                            "start": scene.start,
                            "end": scene.end,
                        },
                    )
                    nodes.append(textnode)
        return nodes
