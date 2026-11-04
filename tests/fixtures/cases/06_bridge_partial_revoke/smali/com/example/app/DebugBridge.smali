.class public Lcom/example/app/DebugBridge;
.super Ljava/lang/Object;
.source "DebugBridge.java"


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method


# virtual methods
.method public dump()Ljava/lang/String;
    .locals 1
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    const-string v0, "dump enabled"

    return-object v0
.end method
