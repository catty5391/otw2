# 此项目用来管理输电塔课题

## 此分支用来考虑风荷载作用

### 继续细分考虑弹塑性材料在脉动风荷载下的作用


1. 定义一种函数关系 load = f(time)  **(这里的load实际只是一种factor乘以后面load内的值才是真正意义上的力)**
```tcl
timeSeries Path $tag -dt $dt -filePath $filePath <-factor $cFactor> <-useLast> <-prependZero> <-startTime $tStart>
```

2. 将函数关系写入pattern
```tcl
pattern Plain $patternTag $tsTag <-fact $cFactor> {
load...
eleLoad...
sp...
...
}
```