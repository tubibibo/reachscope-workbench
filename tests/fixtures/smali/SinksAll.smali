.class public Lcom/example/app/SinkHostActivity;
.super Landroid/app/Activity;
.source "SinkHostActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

# 八类汇点各一例（§5.7）
.method public sinkAll()V
    .locals 6

    # 1 应用私有文件（own：方法内有 getCacheDir 信号）
    invoke-virtual {p0}, Landroid/content/Context;->getCacheDir()Ljava/io/File;
    move-result-object v0
    new-instance v1, Ljava/io/FileInputStream;
    invoke-direct {v1, v0}, Ljava/io/FileInputStream;-><init>(Ljava/io/File;)V

    # 2 外部存储（shared）
    invoke-virtual {p0}, Landroid/content/Context;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;
    move-result-object v0

    # 3 内容提供者：authority 是别家 → cross-app
    const-string v0, "content://com.other.provider/items"
    invoke-static {v0}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v1
    const/4 v2, 0x0
    invoke-virtual {v1, v0, v2, v2, v2}, Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;)Landroid/database/Cursor;

    # 4 命令执行（high）
    const-string v0, "ls"
    invoke-static {}, Ljava/lang/Runtime;->getRuntime()Ljava/lang/Runtime;
    move-result-object v1
    invoke-virtual {v1, v0}, Ljava/lang/Runtime;->exec(Ljava/lang/String;)Ljava/lang/Process;

    # 5 跨组件：Intent 携带数据（shared ≡ §5.7 的 medium）
    new-instance v0, Landroid/content/Intent;
    const-string v1, "com.example.app.ACTION"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const-string v1, "token"
    const-string v2, "secret"
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Landroid/content/Context;->sendBroadcast(Landroid/content/Intent;)V

    # 6 WebView（shared ≡ §5.7 的 medium）
    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V
    const-string v1, "https://cdn.example.com/a.html"
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    # 7 剪贴板（shared ≡ §5.7 的 medium）
    const-string v0, "clipboard"
    invoke-virtual {p0, v0}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;
    move-result-object v0
    check-cast v0, Landroid/content/ClipboardManager;
    invoke-virtual {v0}, Landroid/content/ClipboardManager;->getPrimaryClip()Landroid/content/ClipData;

    # 8 回传调用方：Intent 携带数据（high）
    new-instance v0, Landroid/content/Intent;
    invoke-direct {v0}, Landroid/content/Intent;-><init>()V
    const-string v1, "result"
    const-string v2, "secret"
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    const/4 v1, -0x1
    invoke-virtual {p0, v1, v0}, Landroid/app/Activity;->setResult(ILandroid/content/Intent;)V

    return-void
.end method
