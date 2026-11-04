.class public Lcom/example/app/RegflowTags;
.super Ljava/lang/Object;
.source "RegflowTags.java"

# §6.1 规则 5：field 标签需要一个字段
.field private url:Ljava/lang/String;


# 规则 1：const-string → const
.method public fromConst()Ljava/lang/String;
    .locals 1

    const-string v0, "https://example.com"
    return-object v0
.end method

# 规则 4：Intent.getData() → intent_data
.method public fromIntentData(Landroid/content/Intent;)Ljava/lang/String;
    .locals 1

    invoke-virtual {p1}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    return-object v0
.end method

# 规则 5：Intent.getStringExtra("url") → intent_extra(url)
.method public fromIntentExtra(Landroid/content/Intent;)Ljava/lang/String;
    .locals 2

    const-string v0, "url"
    invoke-virtual {p1, v0}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    return-object v1
.end method

# 规则 6：Uri.getQueryParameter("next") → deeplink_param(next)
.method public fromDeeplinkParam(Landroid/net/Uri;)Ljava/lang/String;
    .locals 2

    const-string v0, "next"
    invoke-virtual {p1, v0}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    return-object v1
.end method

# 规则里没有直接写 field，但 §6.1 的 Tag 枚举里有 field(class,name)
.method public fromField()Ljava/lang/String;
    .locals 1

    iget-object v0, p0, Lcom/example/app/RegflowTags;->url:Ljava/lang/String;
    return-object v0
.end method

# 规则 3：invoke 后紧跟 move-result-object → call_result（本方法内 build() 有实现）
.method public fromCallResult()Ljava/lang/String;
    .locals 1

    invoke-direct {p0}, Lcom/example/app/RegflowTags;->build()Ljava/lang/String;
    move-result-object v0
    return-object v0
.end method

.method private build()Ljava/lang/String;
    .locals 1

    const-string v0, "built"
    return-object v0
.end method

# 规则 7：其他赋值（这里是入参）→ unknown
.method public fromUnknown(Ljava/lang/String;)Ljava/lang/String;
    .locals 0

    return-object p1
.end method
