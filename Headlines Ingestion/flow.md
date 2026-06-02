```
newrawheadlinesingestion-fetchfeedsdata
        ↓
newrawheadlinesingestion-processheadlines
        ↓
newrawheadlinesingestion-imagecdn
        ↓
        ├── Success  → NewRawHeadlinesIngestion_PushToMongoDB
        └── Rejected → newrawheadlinesingestion-rejected-pushtomongo
```