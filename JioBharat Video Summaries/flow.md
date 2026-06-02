```
================================
JioBharat Video Summaries Pipeline
================================

JioBharat_AggregateSummariesPROD
        ↓
Batch Targeted Summary Records
        ↓
jiobharat-pushtosftpprod
        ↓
        ├── Fetch TTS Audio (using sourceId)
        ├── Image Attribution via jionews-de-image-attributor
        │       (Overlay summary title + summary text on thumbnail)
        ↓
Push Attributed Image + TTS Audio + Metadata → SFTP
        ↓
External Processing (Video Creation)
        ↓
Served to JioBharat Devices
```