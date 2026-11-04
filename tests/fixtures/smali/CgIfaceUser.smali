.class public Lcom/example/app/CgIfaceUser;
.super Ljava/lang/Object;

# invoke-interface：静态类型是接口，索引里没有该接口的实现 → target=None, may_dispatch=True
.method public run(Lcom/example/app/CgIf;)V
    .locals 1

    invoke-interface {p1}, Lcom/example/app/CgIf;->doIt()V
    return-void
.end method

# 同一个方法里再调一次具体类：精确签名能连上
.method public direct()V
    .locals 1

    invoke-static {}, Lcom/example/app/CgImpl;->helper()V
    return-void
.end method
