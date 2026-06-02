```
RawSummariesIngestion_FetchFeedsData
        ↓
RawSummariesIngestion_ProcessSummaries
        ↓
newrawheadlinesingestion-imagecdn (generic)
        ↓
        ├── Hygiene Success → RawSummariesIngestion_PushToMongoDB
        ├── Hygiene Failed  → rawsummariesingestion-hyginefailure
        └── Parallel Trigger → jionews-summarization-async (Generating summaries in parallel for the same article using LLMs)
```