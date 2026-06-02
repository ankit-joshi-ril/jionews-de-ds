import type {
  Ticket,
  Notification,
  Requirement,

  FeatureProgress,
  ActivityItem,
  AnalysisResult,
} from "./types";

export const mockTicketsDE: Ticket[] = [
  {
    id: 48201,
    title: "Headlines ingestion pipeline failing for Telugu feeds",
    state: "In Progress",
    type: "Bug",
    priority: 1,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 42",
    description:
      "Telugu RSS feeds from partner ABN Andhra Jyothi are returning 403 errors since April 5th. The headlines-ingestion pipeline is dropping ~200 headlines/day. Redis dedup cache shows no new entries for Telugu since the failure started.",
    tags: ["headlines", "telugu", "p1-critical"],
    createdDate: "2026-04-06T09:15:00+05:30",
    changedDate: "2026-04-08T11:30:00+05:30",
  },
  {
    id: 48195,
    title: "Add JioBharat video summaries for Odia language",
    state: "To Do",
    type: "User Story",
    priority: 2,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 42",
    description:
      "Extend the JioBharat Video Summaries pipeline to support Odia language content. Requires new Gemini prompt configuration, MongoDB collection updates, and Pub/Sub topic routing.",
    tags: ["jiobharat", "odia", "new-language"],
    createdDate: "2026-04-03T14:00:00+05:30",
    changedDate: "2026-04-07T16:45:00+05:30",
  },
  {
    id: 48180,
    title: "Optimize image CDN rendition processing for large thumbnails",
    state: "Dev Complete",
    type: "Task",
    priority: 3,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 42",
    description:
      "Thumbnails above 2MB are causing timeouts in the image-cdn processing step. Need to add progressive JPEG encoding and resize before upload to GCS.",
    tags: ["image-cdn", "performance"],
    createdDate: "2026-04-01T10:00:00+05:30",
    changedDate: "2026-04-08T09:00:00+05:30",
  },
  {
    id: 48165,
    title: "YouTube shorts scraping rate limit handling",
    state: "Ready for QA",
    type: "Bug",
    priority: 2,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 41",
    description:
      "YouTube Data API v3 rate limits are being hit during peak scraping hours (6-9 AM IST). Need exponential backoff and quota management.",
    tags: ["youtube-shorts", "rate-limit"],
    createdDate: "2026-03-28T11:30:00+05:30",
    changedDate: "2026-04-07T14:20:00+05:30",
  },
  {
    id: 48150,
    title: "RSS feed generation latency exceeding 5s SLA",
    state: "To Do",
    type: "Bug",
    priority: 2,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 42",
    description:
      "The rss-feed-generation pipeline is taking 8-12s per feed generation, exceeding the 5s SLA. MongoDB aggregation queries need optimization.",
    tags: ["rss-feed", "performance", "sla-breach"],
    createdDate: "2026-04-05T08:00:00+05:30",
    changedDate: "2026-04-08T10:15:00+05:30",
  },
  {
    id: 48142,
    title: "Webstories ingestion duplicate detection improvement",
    state: "Done",
    type: "Task",
    priority: 3,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 41",
    description:
      "Improve deduplication logic for webstories to handle URL variations (trailing slashes, query params). Current Redis-based dedup is missing ~5% of duplicates.",
    tags: ["webstories", "dedup"],
    createdDate: "2026-03-25T13:00:00+05:30",
    changedDate: "2026-04-04T17:30:00+05:30",
  },
  {
    id: 48130,
    title: "Auto-summarization confidence score calibration",
    state: "In Progress",
    type: "Task",
    priority: 3,
    assignedTo: "Ankit Joshi",
    areaPath: "JioNews-MobileApp\\JioNews-DE-DS",
    iterationPath: "Sprint 42",
    description:
      "Gemini 2.5 Flash confidence scores for auto-summarization are skewing high (avg 0.92). Need to calibrate thresholds and add a quality check pass.",
    tags: ["auto-summarization", "llm", "quality"],
    createdDate: "2026-04-02T09:30:00+05:30",
    changedDate: "2026-04-08T12:00:00+05:30",
  },
];

export const mockTicketsBE: Ticket[] = [
  {
    id: 48210,
    title: "Headlines API pagination not returning correct total count",
    state: "In Progress",
    type: "Bug",
    priority: 2,
    assignedTo: "Rahul Sharma",
    areaPath: "JioNews-MobileApp\\JioNews-Backend",
    iterationPath: "Sprint 42",
    description: "The GET /api/headlines endpoint returns incorrect total count when filters are applied.",
    tags: ["api", "pagination"],
    createdDate: "2026-04-05T10:00:00+05:30",
    changedDate: "2026-04-08T09:00:00+05:30",
  },
  {
    id: 48205,
    title: "Implement caching layer for video metadata API",
    state: "To Do",
    type: "User Story",
    priority: 3,
    assignedTo: "Priya Mehta",
    areaPath: "JioNews-MobileApp\\JioNews-Backend",
    iterationPath: "Sprint 42",
    description: "Add Redis caching for video metadata API to reduce MongoDB load during peak hours.",
    tags: ["caching", "performance"],
    createdDate: "2026-04-04T14:00:00+05:30",
    changedDate: "2026-04-07T11:00:00+05:30",
  },
];

export const mockTicketsFE: Ticket[] = [
  {
    id: 48220,
    title: "Video player controls not responsive on iOS 17",
    state: "In Progress",
    type: "Bug",
    priority: 1,
    assignedTo: "Sneha Patel",
    areaPath: "JioNews-MobileApp\\JioNews-Frontend",
    iterationPath: "Sprint 42",
    description: "Video player overlay controls are unresponsive on iOS 17.4+ devices. Affects ~30% of iOS users.",
    tags: ["ios", "video-player", "p1"],
    createdDate: "2026-04-06T08:00:00+05:30",
    changedDate: "2026-04-08T14:00:00+05:30",
  },
  {
    id: 48215,
    title: "Implement dark mode for webstories viewer",
    state: "To Do",
    type: "User Story",
    priority: 3,
    assignedTo: "Vikram Singh",
    areaPath: "JioNews-MobileApp\\JioNews-Frontend",
    iterationPath: "Sprint 42",
    description: "Add dark mode support for the webstories viewer component.",
    tags: ["dark-mode", "webstories"],
    createdDate: "2026-04-03T11:00:00+05:30",
    changedDate: "2026-04-07T09:00:00+05:30",
  },
];

export const mockTicketsQA: Ticket[] = [
  {
    id: 48225,
    title: "Regression test suite for headlines feed validation",
    state: "In Progress",
    type: "Task",
    priority: 2,
    assignedTo: "Deepika Rao",
    areaPath: "JioNews-MobileApp\\JioNews-QA",
    iterationPath: "Sprint 42",
    description: "Create comprehensive regression tests for the headlines feed validation pipeline.",
    tags: ["testing", "regression", "headlines"],
    createdDate: "2026-04-04T09:00:00+05:30",
    changedDate: "2026-04-08T11:00:00+05:30",
  },
];

export const mockNotifications: Notification[] = [
  {
    id: "n1",
    type: "unblocked",
    title: "You're unblocked on Ticket #48201",
    description: "Backend team completed the API endpoint — DE pipeline work can proceed",
    ticketId: 48201,
    timestamp: "2026-04-08T14:30:00+05:30",
    read: false,
  },
  {
    id: "n2",
    type: "assigned",
    title: "New ticket assigned: #48150",
    description: "RSS feed generation latency exceeding 5s SLA",
    ticketId: 48150,
    timestamp: "2026-04-08T10:15:00+05:30",
    read: false,
  },
  {
    id: "n3",
    type: "comment",
    title: "Product team commented on #48195",
    description: "\"Can we also add Assamese in the same sprint?\"",
    ticketId: 48195,
    timestamp: "2026-04-08T09:00:00+05:30",
    read: false,
  },
  {
    id: "n4",
    type: "completed",
    title: "Feature complete: Webstories Dedup Improvement",
    description: "All teams done — ready for release",
    ticketId: 48142,
    timestamp: "2026-04-07T17:30:00+05:30",
    read: true,
  },
  {
    id: "n5",
    type: "unblocked",
    title: "QA completed testing for #48165",
    description: "YouTube shorts rate limit fix passed all regression tests",
    ticketId: 48165,
    timestamp: "2026-04-07T14:20:00+05:30",
    read: true,
  },
];

export const mockRequirements: Requirement[] = [
  {
    id: "req-001",
    description:
      "We need to support regional language video summaries for JioBharat. Starting with Odia, then Assamese and Punjabi. The summaries should be auto-generated from video transcripts using Gemini.",
    status: "Tickets Created",
    submittedBy: "Meera Kapoor",
    submittedAt: "2026-04-03T10:00:00+05:30",
    ticketDrafts: [
      {
        team: "de",
        title: "Add JioBharat video summaries pipeline for Odia language",
        description: "Extend JioBharat pipeline with Odia language Gemini prompts, MongoDB schema, Pub/Sub routing",
        priority: 2,
        dependencyOrder: 1,
      },
      {
        team: "backend",
        title: "Expose Odia video summaries via content API",
        description: "Add Odia language filter to video summaries API endpoint, update GraphQL schema",
        priority: 2,
        dependencyOrder: 2,
      },
      {
        team: "frontend",
        title: "Display Odia video summaries in app",
        description: "Add Odia to language selector, render video summary cards for Odia content",
        priority: 3,
        dependencyOrder: 3,
      },
      {
        team: "qa",
        title: "Test Odia video summaries end-to-end",
        description: "Validate summary quality, API responses, and UI rendering for Odia language",
        priority: 2,
        dependencyOrder: 4,
      },
    ],
  },
  {
    id: "req-002",
    description:
      "Users are reporting that breaking news headlines are delayed by 5-10 minutes compared to competitors. We need to reduce the ingestion-to-display latency to under 2 minutes.",
    status: "In Progress",
    submittedBy: "Arjun Reddy",
    submittedAt: "2026-04-01T15:30:00+05:30",
  },
  {
    id: "req-003",
    description:
      "Add IPL 2026 live score widget to the home screen with real-time updates. Should support multiple ongoing matches.",
    status: "Draft",
    submittedBy: "Meera Kapoor",
    submittedAt: "2026-04-07T11:00:00+05:30",
  },
];

export const mockFeatureProgress: FeatureProgress[] = [
  {
    id: "feat-001",
    name: "Odia Video Summaries",
    requirement: "Regional language video summaries for JioBharat",
    stages: [
      { team: "product", label: "Requirement", status: "completed", completionPercent: 100 },
      { team: "de", label: "Pipeline", status: "in_progress", ticketId: 48195, assignee: "Ankit Joshi", completionPercent: 35 },
      { team: "backend", label: "API", status: "not_started", completionPercent: 0 },
      { team: "frontend", label: "UI", status: "not_started", completionPercent: 0 },
      { team: "qa", label: "Testing", status: "not_started", completionPercent: 0 },
    ],
  },
  {
    id: "feat-002",
    name: "Headlines Latency Optimization",
    requirement: "Reduce ingestion-to-display latency to under 2 minutes",
    stages: [
      { team: "product", label: "Requirement", status: "completed", completionPercent: 100 },
      { team: "de", label: "Pipeline", status: "completed", assignee: "Ankit Joshi", completionPercent: 100 },
      { team: "backend", label: "API Cache", status: "in_progress", ticketId: 48210, assignee: "Rahul Sharma", completionPercent: 60 },
      { team: "frontend", label: "Real-time UI", status: "not_started", completionPercent: 0 },
      { team: "qa", label: "Latency Tests", status: "not_started", completionPercent: 0 },
    ],
  },
  {
    id: "feat-003",
    name: "Webstories Dedup Improvement",
    requirement: "Fix duplicate webstories appearing in feed",
    stages: [
      { team: "product", label: "Requirement", status: "completed", completionPercent: 100 },
      { team: "de", label: "Dedup Logic", status: "completed", ticketId: 48142, assignee: "Ankit Joshi", completionPercent: 100 },
      { team: "backend", label: "API Update", status: "completed", completionPercent: 100 },
      { team: "frontend", label: "N/A", status: "completed", completionPercent: 100 },
      { team: "qa", label: "Validation", status: "completed", completionPercent: 100 },
    ],
  },
];

export const mockActivityFeed: ActivityItem[] = [
  { id: "a1", team: "de", action: "Completed Telugu feed fix for headlines-ingestion pipeline", ticketId: 48201, timestamp: "2026-04-08T14:30:00+05:30" },
  { id: "a2", team: "qa", action: "Passed regression tests for YouTube shorts rate limit handling", ticketId: 48165, timestamp: "2026-04-08T11:00:00+05:30" },
  { id: "a3", team: "backend", action: "Started implementing Redis caching for video metadata API", ticketId: 48205, timestamp: "2026-04-08T09:30:00+05:30" },
  { id: "a4", team: "de", action: "Pushed image CDN optimization to Dev Complete", ticketId: 48180, timestamp: "2026-04-08T09:00:00+05:30" },
  { id: "a5", team: "frontend", action: "Investigating iOS 17 video player controls issue", ticketId: 48220, timestamp: "2026-04-07T16:00:00+05:30" },
  { id: "a6", team: "product", action: "Submitted new requirement: IPL 2026 Live Score Widget", timestamp: "2026-04-07T11:00:00+05:30" },
  { id: "a7", team: "de", action: "Completed webstories dedup improvement — all tests passing", ticketId: 48142, timestamp: "2026-04-04T17:30:00+05:30" },
];

export const mockAnalysisResult: AnalysisResult = {
  ticketId: 48201,
  affectedPipelines: ["headlines-ingestion"],
  rootCause:
    "The Telugu feed partner ABN Andhra Jyothi has changed their CDN configuration, requiring a new User-Agent header. The current feed fetcher in headlines-ingestion uses a generic UA string that is now blocked with 403.",
  suggestedFix:
    "1. Update the feed fetcher's HTTP headers in `newrawheadlinesingestion-fetchheadlines.py` to include a browser-like User-Agent\n2. Add partner-specific header configuration in the feed config YAML\n3. Implement a fallback mechanism to retry with alternate UA strings on 403 responses\n4. Add alerting for sustained 403 errors per partner",
  affectedFiles: [
    "Headlines Ingestion/newrawheadlinesingestion-fetchheadlines.py",
    "Headlines Ingestion/config/partners.yaml",
  ],
  riskLevel: "Low",
  estimatedEffort: "2-4 hours",
  cached: false,
};
