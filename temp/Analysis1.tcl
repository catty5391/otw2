#分析信息
set numModes 8
#计算n阶振型，并存为lambda数组
set lambda [eigen $numModes]
#定义输出文本文件的名字为"Periods.txt"
set period "output/Periods.txt"
#打开文本文件进行记录
set Periods [open $period "w"]
# 将特征值记录到periods文件中
puts $Periods " $lambda"
# 记录完成，关闭文本文件
close $Periods 
#record