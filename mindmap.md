    # Source videos from Reddit and place them in something like vector
    # src.reddit_client.source_videos()
    src.reddit_client.source_thumbnail()

    # Take every 3rd video, add AI commentary and replace existing one in list (make sure video is long enough to fit commentary)

    # Add credit and fill on sides, stitch them all together and add music chosen randomly from local catalog

    # For thumbnail, use most upvoted image of the day from one of the specified subreddits (add half transparent padding on sides if needed)


Add other keys for gemini. Try to use MistralAI. Add fallback to OpenRouter AIs that use content from the sourced video (using ID to go to post and source them or refactor existing reddit sourcing logic) to get post title, description and top comments and infer commentary from them

<!-- TODO: video sourcing from instagram -->
<!-- TODO: add music relavant to channel niche, decrease original video volume so added music and commentary are more audible -->

