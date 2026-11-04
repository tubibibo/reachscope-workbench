.class public Lcom/example/app/JsBridge;
.super Ljava/lang/Object;
.source "JsBridge.java"

# annotations
.annotation runtime Ldagger/internal/GeneratedComponent;
.end annotation


# virtual methods
.method public readFile(Ljava/lang/String;)Ljava/lang/String;
    .locals 2
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    .line 30
    new-instance v0, Ljava/io/FileInputStream;

    new-instance v1, Ljava/io/File;

    invoke-direct {v1, p0}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    invoke-direct {v0, v1}, Ljava/io/FileInputStream;-><init>(Ljava/io/File;)V

    return-object v0
.end method
