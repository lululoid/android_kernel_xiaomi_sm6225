#CONFIGURATION
DEFCONFIG_PATH=arch/arm64/configs/vendor/fog_defconfig # Must be edited
DEFCONFIG=vendor/fog_defconfig # Must be edited
TAG="[SCRIPT]"

export ARCH=arm64
export SUBARCH=arm64
export PATH="$(pwd)/toolchain/clang/bin:$PATH"

make -j$(nproc) O=out \
	ARCH=arm64 \
	CC=clang \
	HOSTCC=gcc \
	CROSS_COMPILE=aarch64-linux-gnu- \
	CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
	AR=llvm-ar \
	NM=llvm-nm \
	OBJCOPY=llvm-objcopy \
	OBJDUMP=llvm-objdump \
	STRIP=llvm-strip \
	$DEFCONFIG

make -j$(nproc) O=out \
	ARCH=arm64 \
	CC=clang \
	HOSTCC=gcc \
	CROSS_COMPILE=aarch64-linux-gnu- \
	CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
	AR=llvm-ar \
	NM=llvm-nm \
	OBJCOPY=llvm-objcopy \
	OBJDUMP=llvm-objdump \
	STRIP=llvm-strip &&
	cat out/arch/arm64/boot/Image.gz out/arch/arm64/boot/dtb.img >out/arch/arm64/boot/Image.gz-dtb &&
	echo "$TAG    out/arch/arm64/boot/Image.gz-dtb created successfully"
