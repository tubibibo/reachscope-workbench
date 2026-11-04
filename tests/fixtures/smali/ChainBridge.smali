.class public Lcom/example/app/ChainBridge;
.super Ljava/lang/Object;
.source "ChainBridge.java"

# T3.5 的链构造 fixture：桥方法体里有一个文件 sink，
# 链 = `ChainEntry.onCreate → takeAndWrite(deeplink) → FileOutputStream(<init>)`
.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public takeAndWrite(Ljava/lang/String;)V
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    .locals 3
    new-instance v0, Ljava/io/FileOutputStream;
    const-string v1, "/sdcard/x"
    invoke-direct {v0, v1}, Ljava/io/FileOutputStream;-><init>(Ljava/lang/String;)V
    return-void
.end method
